#pragma once

#include <stdint.h>

namespace hardware {

enum class Direction : uint8_t { Clockwise, Counterclockwise };

struct ValvePins {
    uint8_t rightPwm;
    uint8_t leftPwm;
    uint8_t enable;
    uint8_t openLimit;
    uint8_t closedLimit;
    Direction openDirection;
};

constexpr ValvePins kValves[] = {
    {32, 33, 25, 36, 39, Direction::Clockwise},
    {26, 27, 14, 34, 35, Direction::Clockwise},
    {23, 22, 21, 13, 15, Direction::Clockwise},
    {19, 18, 17, 16,  4, Direction::Clockwise},
};

constexpr uint8_t kValveCount = sizeof(kValves) / sizeof(kValves[0]);
constexpr uint32_t kPwmFrequencyHz = 20000;
constexpr uint8_t kPwmResolutionBits = 8;
constexpr uint32_t kMotorDuty = 255;
constexpr uint32_t kReversalDelayMs = 100;
constexpr uint32_t kMaxTravelMs = 120000;
constexpr uint32_t kStatusIntervalMs = 60000;

constexpr bool outputCapable(uint8_t pin) {
    return pin == 4 || (pin >= 13 && pin <= 19) ||
           (pin >= 21 && pin <= 23) || (pin >= 25 && pin <= 27) ||
           pin == 32 || pin == 33;
}

constexpr bool inputCapable(uint8_t pin) {
    return outputCapable(pin) || pin == 34 || pin == 35 || pin == 36 || pin == 39;
}

inline bool validPinMap() {
    bool used[40] = {};
    for (const ValvePins &pins : kValves) {
        if (!outputCapable(pins.rightPwm) || !outputCapable(pins.leftPwm) ||
            !outputCapable(pins.enable) || !inputCapable(pins.openLimit) ||
            !inputCapable(pins.closedLimit)) {
            return false;
        }
        const uint8_t signals[] = {pins.rightPwm, pins.leftPwm, pins.enable,
                                   pins.openLimit, pins.closedLimit};
        for (uint8_t pin : signals) {
            if (used[pin]) return false;
            used[pin] = true;
        }
    }
    return true;
}

static_assert(kValveCount == 4, "Four valve controllers are required");
static_assert(kMotorDuty > 0 && kMotorDuty < (1U << kPwmResolutionBits), "Invalid PWM duty");
static_assert(kMaxTravelMs > 0, "A finite travel timeout is required");

}