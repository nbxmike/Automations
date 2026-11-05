#pragma once

#define MQTT_BROKER_HOST "mqtt.local"
#define MQTT_BROKER_PORT 1883
#define MQTT_CLIENT_ID "thermostat-router"

#if defined(__has_include)
#if __has_include("mqtt_secrets.h")
#include "mqtt_secrets.h"
#endif
#endif

#ifndef MQTT_AUTH_ENABLED
#define MQTT_AUTH_ENABLED 0
#endif

#ifndef MQTT_USERNAME
#define MQTT_USERNAME ""
#endif

#ifndef MQTT_PASSWORD
#define MQTT_PASSWORD ""
#endif