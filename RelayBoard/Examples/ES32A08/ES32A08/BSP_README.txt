*********************************************************
* ES32A08 Board support package "BSP"                   *
* Created by Krőhnung Zsolt                             *
* Version: 1.0 TEST                                     *
* Date: 2026.04.29                                      *
* Free use all OpenPLC projekt                          *
*********************************************************
Board: ES32A08
link : https://485io.com/esp32-board-c-64/es32a08-dc-24v-multifunction-esp32-expansion-board-wifi-digital-analog-io-module-for-arduino-web-mqtt-ethernet-network-relay-diy-p-36.html

MCU  : ESP-WROOM-32 !38PIN!

OpenPLC Editor version: 4.1.4 2026-02-27 

Install :

        Copy ES32A08.cpp => c:\Users\%USERNAME%\AppData\Local\Programs\open-plc-editor\resources\sources\hal\

        Add example_hals_entry.json content to => c:\Users\%USERNAME%\AppData\Local\Programs\open-plc-editor\resources\sources\boards\hals.json

        Copy driver folder to "BoardDriver_ES32A08" => c:\Users\%USERNAME%\AppData\Local\Arduino15\packages\esp32\hardware\esp32\3.3.7\libraries\

        Import ES32A08_Empty project configured pins and global variables

Dev use information:

             Modbus:
                                                         4x0 ... 4x19 Retentive Memory Variable
                                                        4x20 ...4x29 Normal Variable 

                 IO:
                    Analog 0-20mA                     %IW0   ... %IW3
                    Analog 0-10V                      %IW4   ... %IW7
                    Key1 - Key4                       %IX0.0 ... %IX0.3      (Integrated IO)
                    DI 1-8                            %IX0.4 ... %IX1.3      (SN165N Shiftregister Inputs)
                    Relay Out 1-8                     %QX0.1 ... %QX1.0      (SN595 Shiftregister Outs)

                    Retentive Memory Shared Modbus    %QW0   ... %QW19       (Using Storage)
                    Normal Memory Shared Modbus       %QW20  ... %QW29       (NOT USE Storage)

                    Extra function block:             getBitsModbus                  : Input UINT value Out Bit status all 16bit position
                                                      setBitsModbus                  : Input 16 bool setting Out 16bit UINT number
                                                      remapAnalaogInputUINT          : Remap Analaog input value linear
                                                      rateLimiterAnalogInputUINT     :
                                                      lowPassFilterAnalogInputUINT   :
                                                      write7SegmentDisplay           : Write STRING 4X7 intergrated seven segment display

Other information:
                   Modbus en pin: 22

