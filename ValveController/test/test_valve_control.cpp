#include <assert.h>
#include <initializer_list>
#include <stdio.h>

#include "valve_config.h"
#include "valve_control.h"

using valve::Command;
using valve::Control;
using valve::Limits;
using valve::Motion;
using valve::Status;

int main() {
    assert(hardware::validPinMap());
    const Limits between{false, false};
    const Limits opened{true, false};
    const Limits closed{false, true};
    const Limits fault{true, true};

    for (const char *text : {"open", "on", "close", "off", "OPEN", "", "openx"}) {
        const Command expected = strcmp(text, "open") == 0 || strcmp(text, "on") == 0
            ? Command::Open : strcmp(text, "close") == 0 || strcmp(text, "off") == 0
            ? Command::Close : Command::Invalid;
        assert(valve::parseCommand(reinterpret_cast<const uint8_t *>(text), strlen(text)) == expected);
    }
    const uint8_t embeddedNull[] = {'o', 'n', 0};
    assert(valve::parseCommand(embeddedNull, sizeof(embeddedNull)) == Command::Invalid);

    for (const Limits limits : {between, opened, closed, fault}) {
        for (const Command command : {Command::Open, Command::Close}) {
            Control control;
            assert(control.status(limits) == (limits.open && limits.closed ? Status::Error
                : limits.open ? Status::Open : limits.closed ? Status::Closed : Status::Unknown));
            control.request(command, limits, 1000);
            const bool blocked = command == Command::Open ? limits.open : limits.closed;
            assert(control.motion() == (blocked ? Motion::Stopped
                : command == Command::Open ? Motion::Opening : Motion::Closing));
            if (!blocked) {
                assert(control.status(between) == (command == Command::Open ? Status::Opening : Status::Closing));
                control.update(command == Command::Open ? opened : closed, 1001);
                assert(control.motion() == Motion::Stopped);
            }
        }
    }

    for (const Command command : {Command::Open, Command::Close}) {
        for (const Limits limits : {between, opened, closed, fault}) {
            Control running;
            running.request(command, between, 1000);
            const Status expected = limits.open && limits.closed ? Status::Error
                : limits.open ? Status::Open : limits.closed ? Status::Closed
                : command == Command::Open ? Status::Opening : Status::Closing;
            assert(running.status(limits) == expected);
            running.request(Command::Invalid, between, 1001);
            running.update(limits, 1002);
            const bool stopped = command == Command::Open ? limits.open : limits.closed;
            assert((running.motion() == Motion::Stopped) == stopped);
        }
    }
    assert(strcmp(valve::statusName(Status::Open), "open") == 0);
    assert(strcmp(valve::statusName(Status::Closed), "closed") == 0);
    assert(strcmp(valve::statusName(Status::Opening), "opening") == 0);
    assert(strcmp(valve::statusName(Status::Closing), "closing") == 0);
    assert(strcmp(valve::statusName(Status::Error), "error") == 0);
    assert(strcmp(valve::statusName(Status::Unknown), "unknown") == 0);

    Control control;
    control.request(Command::Open, closed, 1000);
    control.update(fault, 1001);
    assert(control.motion() == Motion::Stopped);
    assert(control.status(fault) == Status::Error);
    control.update(between, 2000);
    assert(control.motion() == Motion::Stopped);

    control.request(Command::Open, between, 2000);
    control.request(Command::Close, between, 2010);
    assert(control.motion() == Motion::Stopped);
    assert(control.status(between) == Status::Unknown);
    control.update(between, 2109);
    assert(control.motion() == Motion::Stopped);
    control.request(Command::Close, between, 2109);
    assert(control.motion() == Motion::Stopped);
    control.update(between, 2110);
    assert(control.motion() == Motion::Closing);
    control.request(Command::Close, between, 2200);
    control.update(between, 122110);
    assert(control.motion() == Motion::Stopped);
    assert(control.status(between) == Status::Unknown);

    Control pending;
    pending.request(Command::Open, between, 0);
    pending.update(opened, 50);
    pending.update(between, 200);
    assert(pending.motion() == Motion::Stopped);

    Control rollover;
    rollover.request(Command::Open, between, UINT32_MAX - 50);
    rollover.request(Command::Close, between, UINT32_MAX - 10);
    rollover.update(between, 88);
    assert(rollover.motion() == Motion::Stopped);
    rollover.update(between, 89);
    assert(rollover.motion() == Motion::Closing);

    Control independent[4];
    independent[0].request(Command::Open, between, 1000);
    independent[1].request(Command::Close, between, 1000);
    independent[0].update(opened, 1100);
    assert(independent[0].motion() == Motion::Stopped);
    assert(independent[1].motion() == Motion::Closing);
    assert(independent[2].motion() == Motion::Stopped);
    assert(independent[3].motion() == Motion::Stopped);
    puts("Valve control tests passed.");
}