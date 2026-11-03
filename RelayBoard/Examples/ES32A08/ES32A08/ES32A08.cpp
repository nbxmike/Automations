#include <stdlib.h>
extern "C" {
 #include "openplc.h"
}
#include "Arduino.h"
//#include <WString.h>
#include "../examples/Baremetal/defines.h"
//#include "driver/ledc.h"
#include <BoardDriver_ES32A08.h>
// OpenPLC HAL for ESP32 boards
// NOTE: PWM channel == pin number

uint16_t eepromCache[MAX_SLOTS];

// Create the I/O pin masks (defined within editor GUI when compiling for board)
uint8_t pinMask_DIN[] = {PINMASK_DIN};
uint8_t pinMask_AIN[] = {PINMASK_AIN};
uint8_t pinMask_DOUT[] = {PINMASK_DOUT};
uint8_t pinMask_AOUT[] = {PINMASK_AOUT};

#define PWM_ANALOG_FREQ       4000 // Frequency to use when emulating analog on boards without a DAC
#define PWM_RESOLUTION        12 // 12-bit should allow up to 10kHz
#define PWM_MAX               0xFFF // 12-bit max

extern "C" uint8_t set_hardware_pwm(uint8_t, float, float); //this call is required for the C-based PWM block on the Editor
bool pwm_initialized[64] = {false}; // Store which PWM channels have been initialised
void hardwareInit()
{
    ///////////////////////////////////
    // Setup EPROM Function
    ///////////////////////////////////
    EEPROM.begin(EEPROM_SIZE);
    setupSlots();
    for (int i = 0; i < MAX_SLOTS; i++) {
        eepromCache[i] = readFromSlot(i);
    }
    
    //////////////////////////////////
    // Setup Shiftregister inputs
    //////////////////////////////////
    pinMode(ES32_165N_load_pin, OUTPUT);
    pinMode(ES32_165N_clockIn_pin, OUTPUT);
    pinMode(ES32_165N_dataIn_pin, INPUT);
    
    //////////////////////////////////
    // Setup Shiftregister outputs
    //////////////////////////////////
    pinMode(ES32_595N_DATA_PIN, OUTPUT);
    pinMode(ES32_595N_CLOCK_PIN, OUTPUT);
    pinMode(ES32_595N_LATCH_PIN, OUTPUT);
    pinMode(ES32_595N_OE_PIN, OUTPUT);
    digitalWrite(ES32_595N_OE_PIN, LOW);

    ES32_setupCharMap();

    for (int i = 0; i < NUM_DISCRETE_INPUT; i++)
    {
        if (i != 0 || i != 1 || i != 2 || i != 3) {pinMode(pinMask_DIN[i], INPUT);}
	if (i == 0) pinMode(pinMask_DIN[i], INPUT_PULLUP);
	if (i == 1) pinMode(pinMask_DIN[i], INPUT_PULLUP);
	if (i == 2) pinMode(pinMask_DIN[i], INPUT_PULLUP);
	if (i == 3) pinMode(pinMask_DIN[i], INPUT_PULLUP);
    }

    for (int i = 0; i < NUM_DISCRETE_OUTPUT; i++)
    {
        pinMode(pinMask_DOUT[i], OUTPUT);
    }
    for (int i = 0; i < NUM_ANALOG_OUTPUT; i++)
    {
        /*  It’s assumed that cards with real DAC’s only have two channels and they are the first two assigned pins in the HAL file or 
        the IDE config. More than two defined pins are assumed to be PWM analog channels.
        Modified the line below so if the card has a real DAC the output gets set as an output, if not its set for PWM output
        If the card does not have a real DAC all defined analog output pins ar set for PWM
        */

        #if (SOC_DAC_SUPPORTED)
            if (i < 2)
            { 
                pinMode(pinMask_AOUT[i], OUTPUT);
            }
            else	
            {	
                ledcAttach(pinMask_AOUT[i], PWM_ANALOG_FREQ, PWM_RESOLUTION);
            }
        #else
            ledcAttach(pinMask_AOUT[i], PWM_ANALOG_FREQ, PWM_RESOLUTION);
        #endif
    }

    for (int i = 0; i < NUM_ANALOG_OUTPUT; i++)
    {
        if (int_output[i] != NULL)
        {
            uint16_t rawValue;
            if (pinMask_AOUT[i] >= 100 && pinMask_AOUT[i] < 199) {   // Virtuális csatorna
                uint8_t slot = pinMask_AOUT[i] - 100;
                if (slot < MAX_SLOTS) {
                    rawValue = eepromCache[slot];
                } else {
                    rawValue = 0;
                }
            } else {   // Fizikai analóg bemenet
                rawValue = analogRead(pinMask_AOUT[i]) * 16;   // 0-4095 -> 0-65520, de a *16 miatt 0-65520 (majdnem 16 bites)
            }
            *int_output[i] = rawValue;
        }
    }
}

uint8_t set_hardware_pwm(uint8_t ch, float freq, float duty)
{
    if (!pwm_initialized[ch])
    {
        if (!ledcAttach(ch, (uint32_t)freq, PWM_RESOLUTION))
        {
            return 0;
        }
        pwm_initialized[ch] = true;
    }

    ledcWrite(ch, (uint32_t)(duty / 100 * PWM_MAX));
    return ledcChangeFrequency(ch, (uint32_t)freq, PWM_RESOLUTION);
}
bool isPhysicalAnalog(int pin) {
    return (pin == 25 || pin == 26 || pin == 32 || pin == 33 || pin == 34 || pin == 35 || pin == 36 || pin == 39);
}
byte ES32_InputsValues = 0;
int  ES32_InputsPinNumber = 0;
void updateInputBuffers()
{
///////////////////// Hardware input //////////////////////////////////
    // Write pulse to load pin
    digitalWrite(ES32_165N_load_pin, LOW);
//    delayMicroseconds(5);
    digitalWrite(ES32_165N_load_pin, HIGH);
//    delayMicroseconds(5);
   
    ES32_InputsValues = shiftIn(ES32_165N_dataIn_pin, ES32_165N_clockIn_pin, LSBFIRST);
///////////////////////////////////////////////////////////////////////
    ES32_InputsPinNumber = 7;
    for (int i = 0; i < NUM_DISCRETE_INPUT; i++)
    {
        if (bool_input[i/8][i%8] != NULL)
           if (pinMask_DIN[i] < 80){ 
              if (pinMask_DIN[i] != 18 || pinMask_DIN[i] != 19 || pinMask_DIN[i] != 21 || pinMask_DIN[i] != 23){ 
                 *bool_input[i/8][i%8] = digitalRead(pinMask_DIN[i]);
              }
              if (pinMask_DIN[i] == 18 || pinMask_DIN[i] == 19 || pinMask_DIN[i] == 21 || pinMask_DIN[i] == 23) {
                 *bool_input[i/8][i%8] = !digitalRead(pinMask_DIN[i]);
              }
           }
           if (pinMask_DIN[i] >= 80 && pinMask_DIN[i] < 88){ 
              
              *bool_input[i/8][i%8] = !ES32_get_bit(ES32_InputsValues, ES32_InputsPinNumber);
               ES32_InputsPinNumber--;
              
           }
    }


    for (int i = 0; i < NUM_ANALOG_INPUT; i++)
    {
	int pin = pinMask_AIN[i];
        if (int_input[i] != NULL && isPhysicalAnalog(pin)){
            *int_input[i] = (analogRead(pinMask_AIN[i]) * 16); // changed from 64 to 16 
        }
    }

}
bool CommitToNanand = false;   // jobb a bool típus
void updateOutputBuffers()
{
//////////////////////////////////////////////////////////////////////////////////////
/////////////////////////
//////////////////////////////////////////////////////////////////////////////////////
    for (int j = 0; j < NUM_ANALOG_OUTPUT; j++)
    {
        int pin = pinMask_AOUT[j];
        if ( int_input[j] != NULL && !isPhysicalAnalog(pin) && pinMask_AOUT[j] < 199 )   // csak virtuális csatornák
        {
            uint8_t slot = pin - 100;          // mert a virtuális pin-ek 100-tól indulnak
            if (slot < MAX_SLOTS)
            {
                uint16_t newValue = *int_output[j];
                if (eepromCache[slot] != newValue)
                {
                    eepromCache[slot] = newValue;
                    writeToSlot(slot, newValue);
                    CommitToNanand = true;
                }
            }
        }
    }

    // Commit, ha volt változás
    if (CommitToNanand)
    {
        commitChanges();
        CommitToNanand = false;
    }
//////////////////////////////////////////////////////////////////////////////////////
    int ES32_OutPinNumber = 1;
    for (int i = 0; i < NUM_DISCRETE_OUTPUT; i++)
    {
        if (bool_output[i/8][i%8] != NULL){
            if (pinMask_DOUT[i] < 90){
              digitalWrite(pinMask_DOUT[i], *bool_output[i/8][i%8]);
            }
            if (pinMask_DOUT[i] >= 90 && pinMask_DOUT[i] < 98){ 
              ES32_setRelay(ES32_OutPinNumber, *bool_output[i/8][i%8]);
              ES32_OutPinNumber++;
            }
        }
    }
ES32_writeRegs();

    /*for (int i = 0; i < NUM_ANALOG_OUTPUT; i++)
    {
        if (int_output[i] != NULL)
        {
            // Modified the line below so if the loop index "i" is < 2 that means the channel is a real DAC if > 2 then its a PWM analog output
            
            #if (SOC_DAC_SUPPORTED )
                if (i < 2)
                {
                    dacWrite(pinMask_AOUT[i], (*int_output[i] / 256));
                }
                else
                {
                    ledcWrite(pinMask_AOUT[i], (*int_output[i] / 16));
                }
            #else
                ledcWrite(pinMask_AOUT[i], (*int_output[i] / 16));
            #endif
        }
    }*/
}
