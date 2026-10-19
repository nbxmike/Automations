# Name Changes for MQTT Device/Topic Compatibility

| Type | Old name/topic | New name/topic |
|---|---|---|
| Device name | `late_arrival_override` | `lateArrivalOverride` |
| Device name | `wyze_parking_tree` | `wyzeParkingTree` |
| Topic root | `phone_presence` | `phonePresence` |
| Discovery unique_id | `virtual_late_arrival_override_01` | `virtualLateArrivalOverride01` |
| Discovery unique_id | `virtual_kitchen_spectral_01` | `virtualKitchenSpectral01` |
| MQTT topic | `cmnd/wyze_parking_tree/POWER1` | `cmnd/wyzeParkingTree/POWER1` |
| MQTT topic | `cmnd/wyze_parking_tree/POWER2` | `cmnd/wyzeParkingTree/POWER2` |
| MQTT topic | `stat/wyze_parking_tree/POWER1` | `stat/wyzeParkingTree/POWER1` |
| MQTT topic | `stat/wyze_parking_tree/POWER2` | `stat/wyzeParkingTree/POWER2` |
| MQTT topic | `stat/late_arrival_override/POWER` | `stat/lateArrivalOverride/POWER` |
| MQTT topic | `stat/late_arrival_override/STATE` | `stat/lateArrivalOverride/STATE` |
| MQTT topic | `lights/late_arrival_override/set` | `lights/lateArrivalOverride/set` |
| MQTT topic | `lights/late_arrival_override/state` | `lights/lateArrivalOverride/state` |
| MQTT topic | `homeassistant/light/late_arrival_override/config` | `homeassistant/light/lateArrivalOverride/config` |
| MQTT topic | `cmnd/kitchenSpectral/BRIGHTNESS` | `cmnd/kitchenSpectral/brightness` |
| MQTT topic | `cmnd/kitchenSpectral/BRIGHTNESS_WITH_ONOFF` | `cmnd/kitchenSpectral/brightnessWithOnOff` |
| MQTT topic | `cmnd/kitchenSpectral/COLOR_TEMP` | `cmnd/kitchenSpectral/colorTemp` |
| MQTT topic | `cmnd/kitchenSpectral/COLOR_TEMP_WITH_ONOFF` | `cmnd/kitchenSpectral/colorTempWithOnOff` |
| MQTT topic | `stat/kitchenSpectral/BRIGHTNESS` | `stat/kitchenSpectral/brightness` |
| MQTT topic | `stat/kitchenSpectral/COLOR_TEMP` | `stat/kitchenSpectral/colorTemp` |
| MQTT topic | `girier_01/11/set` | `girier01/11/set` |
| MQTT topic | `girier_01/11/get` | `girier01/11/get` |
| MQTT topic pattern | `phone_presence/<person>` | `phonePresence/<person>` |
| MQTT topic | `phone_presence/everyone` | `phonePresence/everyone` |
| Generated leaf pattern | `<name>_<last4mac>` | `<name><last4mac>` |
