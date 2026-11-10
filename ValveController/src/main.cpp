#include <Arduino.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

#include "mqtt_config.h"
#include "valve_config.h"
#include "valve_control.h"

namespace {

constexpr uint32_t kReconnectIntervalMs = 5000;
constexpr char kBaseTopic[] = MQTT_ROOT_TOPIC;
constexpr char kAvailabilityTopic[] = MQTT_ROOT_TOPIC "/availability";
static_assert(sizeof(kBaseTopic) < 80, "MQTT root topic is too long");

WiFiClient networkClient;
PubSubClient mqttClient(networkClient);
QueueHandle_t commandQueues[hardware::kValveCount] = {};
std::atomic<valve::Status> statuses[hardware::kValveCount];
valve::Status publishedStatuses[hardware::kValveCount] = {};
bool publishedValid[hardware::kValveCount] = {};
uint8_t nextStatusValve = 0;
uint32_t nextStatusAt = 0;
uint32_t nextChangeReportAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t lastMqttAttemptAt = 0;
bool wifiAttempted = false;
bool mqttAttempted = false;

valve::Limits readLimits(uint8_t index) {
    const hardware::ValvePins &pins = hardware::kValves[index];
    return {digitalRead(pins.openLimit) == LOW, digitalRead(pins.closedLimit) == LOW};
}

void applyMotor(uint8_t index, valve::Motion motion) {
    const hardware::ValvePins &pins = hardware::kValves[index];
    const uint8_t rightChannel = index * 2;
    const uint8_t leftChannel = rightChannel + 1;
    digitalWrite(pins.enable, LOW);
    ledcWriteChannel(rightChannel, 0);
    ledcWriteChannel(leftChannel, 0);
    if (motion == valve::Motion::Stopped) {
        return;
    }

    const bool clockwise = (motion == valve::Motion::Opening) ==
                           (pins.openDirection == hardware::Direction::Clockwise);
    ledcWriteChannel(clockwise ? rightChannel : leftChannel, hardware::kMotorDuty);
    digitalWrite(pins.enable, HIGH);
}

void motorTask(void *) {
    valve::Control controls[hardware::kValveCount] = {
        valve::Control(hardware::kReversalDelayMs, hardware::kMaxTravelMs),
        valve::Control(hardware::kReversalDelayMs, hardware::kMaxTravelMs),
        valve::Control(hardware::kReversalDelayMs, hardware::kMaxTravelMs),
        valve::Control(hardware::kReversalDelayMs, hardware::kMaxTravelMs),
    };
    valve::Motion applied[hardware::kValveCount] = {};

    for (;;) {
        const uint32_t now = millis();
        for (uint8_t index = 0; index < hardware::kValveCount; ++index) {
            const valve::Limits limits = readLimits(index);
            valve::Command command;
            if (xQueueReceive(commandQueues[index], &command, 0) == pdTRUE) {
                controls[index].request(command, limits, now);
            }
            controls[index].update(limits, now);
            const valve::Motion motion = controls[index].motion();
            if (motion != applied[index]) {
                applyMotor(index, motion);
                applied[index] = motion;
            }
            statuses[index].store(controls[index].status(limits));
        }
        vTaskDelay(1);
    }
}

bool publishValveStatus(uint8_t index) {
    char topic[128];
    snprintf(topic, sizeof(topic), "%s/valve%u/state", kBaseTopic, index + 1);
    const valve::Status status = statuses[index].load();
    if (!mqttClient.publish(topic, valve::statusName(status), true)) {
        return false;
    }
    publishedStatuses[index] = status;
    publishedValid[index] = true;
    return true;
}

void onMqttMessage(char *topic, byte *payload, unsigned int length) {
    const valve::Command command = valve::parseCommand(payload, length);
    if (command == valve::Command::Invalid) {
        return;
    }
    for (uint8_t index = 0; index < hardware::kValveCount; ++index) {
        char directTopic[128];
        char setTopic[128];
        snprintf(directTopic, sizeof(directTopic), "%s/valve%u", kBaseTopic, index + 1);
        snprintf(setTopic, sizeof(setTopic), "%s/valve%u/set", kBaseTopic, index + 1);
        if (strcmp(topic, directTopic) == 0 || strcmp(topic, setTopic) == 0) {
            xQueueOverwrite(commandQueues[index], &command);
            return;
        }
    }
}

void maintainWifi(uint32_t now) {
    if (WiFi.status() == WL_CONNECTED) {
        return;
    }
    if (!wifiAttempted || now - lastWifiAttemptAt >= kReconnectIntervalMs) {
        wifiAttempted = true;
        lastWifiAttemptAt = now;
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
}

void maintainMqtt(uint32_t now) {
    if (WiFi.status() != WL_CONNECTED || mqttClient.connected()) {
        return;
    }
    if (mqttAttempted && now - lastMqttAttemptAt < kReconnectIntervalMs) {
        return;
    }
    mqttAttempted = true;
    lastMqttAttemptAt = now;
    bool connected;
#if MQTT_AUTH_ENABLED
    connected = mqttClient.connect(MQTT_CLIENT_ID, MQTT_USERNAME, MQTT_PASSWORD,
                                   kAvailabilityTopic, 0, true, "offline");
#else
    connected = mqttClient.connect(MQTT_CLIENT_ID, kAvailabilityTopic, 0, true, "offline");
#endif
    if (connected) {
        const bool directSubscribed = mqttClient.subscribe(MQTT_ROOT_TOPIC "/+", 1);
        const bool setSubscribed = mqttClient.subscribe(MQTT_ROOT_TOPIC "/+/set", 1);
        if (!directSubscribed || !setSubscribed ||
            !mqttClient.publish(kAvailabilityTopic, "online", true)) {
            mqttClient.disconnect();
            return;
        }
        for (uint8_t index = 0; index < hardware::kValveCount; ++index) {
            publishedValid[index] = false;
        }
    }
}

void reportStatuses(uint32_t now) {
    if (!mqttClient.connected()) {
        return;
    }
    if (static_cast<int32_t>(now - nextChangeReportAt) >= 0) {
        for (uint8_t index = 0; index < hardware::kValveCount; ++index) {
            if (!publishedValid[index] || statuses[index].load() != publishedStatuses[index]) {
                publishValveStatus(index);
            }
        }
        nextChangeReportAt = now + 100;
    }
    if (static_cast<int32_t>(now - nextStatusAt) >= 0) {
        if (publishValveStatus(nextStatusValve)) {
            nextStatusValve = (nextStatusValve + 1) % hardware::kValveCount;
            nextStatusAt = now + hardware::kStatusIntervalMs;
        } else {
            nextStatusAt = now + 2000;
        }
    }
}

[[noreturn]] void halt(const char *reason) {
    Serial.println(reason);
    for (;;) {
        delay(1000);
    }
}

}

void setup() {
    Serial.begin(115200);
    if (!hardware::validPinMap()) {
        halt("Invalid valve GPIO map; controller disabled.");
    }

    for (const hardware::ValvePins &pins : hardware::kValves) {
        digitalWrite(pins.enable, LOW);
        pinMode(pins.enable, OUTPUT);
    }
    for (uint8_t index = 0; index < hardware::kValveCount; ++index) {
        const hardware::ValvePins &pins = hardware::kValves[index];
        digitalWrite(pins.rightPwm, LOW);
        digitalWrite(pins.leftPwm, LOW);
        pinMode(pins.rightPwm, OUTPUT);
        pinMode(pins.leftPwm, OUTPUT);
        pinMode(pins.openLimit, INPUT);
        pinMode(pins.closedLimit, INPUT);
        for (uint8_t side = 0; side < 2; ++side) {
            const uint8_t channel = index * 2 + side;
            if (!ledcAttachChannel(side == 0 ? pins.rightPwm : pins.leftPwm,
                                   hardware::kPwmFrequencyHz,
                                   hardware::kPwmResolutionBits, channel)) {
                halt("PWM setup failed; controller disabled.");
            }
            ledcWriteChannel(channel, 0);
        }
        commandQueues[index] = xQueueCreate(1, sizeof(valve::Command));
        if (commandQueues[index] == nullptr) {
            halt("Command queue allocation failed; controller disabled.");
        }
        statuses[index].store(valve::Control().status(readLimits(index)));
    }
    if (xTaskCreatePinnedToCore(motorTask, "valve-motors", 4096, nullptr, 3,
                              nullptr, 1) != pdPASS) {
        halt("Motor task creation failed; controller disabled.");
    }

    WiFi.mode(WIFI_STA);
    mqttClient.setServer(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
    mqttClient.setCallback(onMqttMessage);
    mqttClient.setSocketTimeout(1);
    mqttClient.setKeepAlive(30);
    mqttClient.setBufferSize(512);
    nextStatusAt = millis() + hardware::kStatusIntervalMs;
}

void loop() {
    const uint32_t now = millis();
    maintainWifi(now);
    maintainMqtt(now);
    if (mqttClient.connected()) {
        mqttClient.loop();
    }
    reportStatuses(millis());
    delay(2);
}