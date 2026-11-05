#include <Arduino.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include "mqtt_config.h"
#include "../wifi_secrets.h"

namespace {

constexpr uint8_t kDataPin = 13;
constexpr uint8_t kClockPin = 27;
constexpr uint8_t kLatchPin = 14;
constexpr uint8_t kOutputEnablePin = 4;
constexpr uint8_t kZoneCount = 4;
constexpr uint32_t kReconnectIntervalMs = 5000;
constexpr uint32_t kStatusIntervalMs = 120000;
constexpr uint32_t kHeartbeatPeriodMs = 25000;
constexpr uint32_t kHeartbeatDurationMs = 5000;
constexpr char kBaseTopic[] = "thermostat-router";
constexpr char kAvailabilityTopic[] = "thermostat-router/availability";

enum class ZoneState : uint8_t {
    Bypass,
    On,
    Off,
};

ZoneState zoneStates[kZoneCount] = {
    ZoneState::Bypass,
    ZoneState::Bypass,
    ZoneState::Bypass,
    ZoneState::Bypass,
};

constexpr uint8_t kDigitSelects[4] = {0xFE, 0xFD, 0xFB, 0xF7};
WiFiClient networkClient;
PubSubClient mqttClient(networkClient);
uint8_t relayBits = 0;
uint8_t nextStatusZone = 0;
uint32_t nextStatusAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t lastMqttAttemptAt = 0;
bool wifiAttempted = false;
bool mqttAttempted = false;

const char *stateName(ZoneState state) {
    switch (state) {
    case ZoneState::On:
        return "on";
    case ZoneState::Off:
        return "off";
    case ZoneState::Bypass:
    default:
        return "bypass";
    }
}

char displayCharacter(ZoneState state) {
    switch (state) {
    case ZoneState::On:
        return '1';
    case ZoneState::Off:
        return '0';
    case ZoneState::Bypass:
    default:
        return 'b';
    }
}

uint8_t segmentPattern(char value) {
    switch (value) {
    case '0':
        return 0x3F;
    case '1':
        return 0x06;
    case 'b':
        return 0x7C;
    case '-':
        return 0x40;
    default:
        return 0x00;
    }
}

void setRelay(uint8_t relayNumber, bool energized) {
    if (relayNumber < 1 || relayNumber > 8) {
        return;
    }

    const uint8_t bit = static_cast<uint8_t>(1U << (relayNumber - 1));
    if (energized) {
        relayBits |= bit;
    } else {
        relayBits &= static_cast<uint8_t>(~bit);
    }
}

void applyZoneRelays() {
    for (uint8_t zone = 0; zone < kZoneCount; ++zone) {
        const uint8_t oddRelay = static_cast<uint8_t>(zone * 2 + 1);
        const bool energizeOdd = zoneStates[zone] == ZoneState::On;
        const bool energizeEven = zoneStates[zone] != ZoneState::Bypass;
        setRelay(oddRelay, energizeOdd);
        setRelay(static_cast<uint8_t>(oddRelay + 1), energizeEven);
    }
}

void refreshDisplay(uint32_t now) {
    const bool heartbeat = now % kHeartbeatPeriodMs < kHeartbeatDurationMs;

    for (uint8_t digit = 0; digit < 4; ++digit) {
        const char value = heartbeat ? '-' : displayCharacter(zoneStates[digit]);
        digitalWrite(kLatchPin, LOW);
        shiftOut(kDataPin, kClockPin, MSBFIRST, relayBits);
        shiftOut(kDataPin, kClockPin, MSBFIRST, kDigitSelects[digit]);
        shiftOut(kDataPin, kClockPin, MSBFIRST, segmentPattern(value));
        digitalWrite(kLatchPin, HIGH);
        delay(5);
    }
}

bool publishZoneState(uint8_t zone) {
    char topic[64];
    snprintf(topic, sizeof(topic), "%s/zone%u/state", kBaseTopic, zone + 1);
    return mqttClient.publish(topic, stateName(zoneStates[zone]), true);
}

void onMqttMessage(char *topic, byte *payload, unsigned int length) {
    if (length == 0 || length >= 16) {
        return;
    }

    char command[16];
    memcpy(command, payload, length);
    command[length] = '\0';

    for (uint8_t zone = 0; zone < kZoneCount; ++zone) {
        char expectedTopic[64];
        snprintf(expectedTopic, sizeof(expectedTopic), "%s/zone%u/set", kBaseTopic, zone + 1);
        if (strcmp(topic, expectedTopic) != 0) {
            continue;
        }

        if (strcmp(command, "bypass") == 0) {
            zoneStates[zone] = ZoneState::Bypass;
        } else if (strcmp(command, "on") == 0) {
            zoneStates[zone] = ZoneState::On;
        } else if (strcmp(command, "off") == 0) {
            zoneStates[zone] = ZoneState::Off;
        } else {
            return;
        }

        applyZoneRelays();
        publishZoneState(zone);
        return;
    }
}

void maintainWifi(uint32_t now) {
    if (WiFi.status() == WL_CONNECTED) {
        return;
    }

    if (!wifiAttempted || now - lastWifiAttemptAt >= kReconnectIntervalMs) {
        wifiAttempted = true;
        lastWifiAttemptAt = now;
        WiFi.mode(WIFI_STA);
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
        mqttClient.publish(kAvailabilityTopic, "online", true);
        mqttClient.subscribe("thermostat-router/+/set", 1);
    }
}

void publishNextZoneStatus(uint32_t now) {
    if (!mqttClient.connected() || static_cast<int32_t>(now - nextStatusAt) < 0) {
        return;
    }

    if (publishZoneState(nextStatusZone)) {
        nextStatusZone = static_cast<uint8_t>((nextStatusZone + 1) % kZoneCount);
        nextStatusAt = now + kStatusIntervalMs;
    } else {
        nextStatusAt = now + 2000;
    }
}

} // namespace

void setup() {
    Serial.begin(115200);

    pinMode(kDataPin, OUTPUT);
    pinMode(kClockPin, OUTPUT);
    pinMode(kLatchPin, OUTPUT);
    pinMode(kOutputEnablePin, OUTPUT);
    digitalWrite(kOutputEnablePin, HIGH);
    digitalWrite(kDataPin, LOW);
    digitalWrite(kClockPin, LOW);
    digitalWrite(kLatchPin, HIGH);

    applyZoneRelays();
    mqttClient.setServer(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
    mqttClient.setCallback(onMqttMessage);
    mqttClient.setSocketTimeout(1);
    mqttClient.setKeepAlive(30);

    nextStatusAt = millis() + kStatusIntervalMs;
    refreshDisplay(millis());
    digitalWrite(kOutputEnablePin, LOW);
}

void loop() {
    const uint32_t now = millis();
    maintainWifi(now);
    maintainMqtt(now);
    if (mqttClient.connected()) {
        mqttClient.loop();
    }
    publishNextZoneStatus(now);
    refreshDisplay(now);
}