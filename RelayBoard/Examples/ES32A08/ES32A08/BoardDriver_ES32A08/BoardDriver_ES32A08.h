#ifndef ES32A08_h
#define ES32A08_h

#include "Arduino.h"
#include <EEPROM.h>      // Mert a függvények használják az EEPROM-ot
// ========== Eprom configuration ==========
// Konstansok
#define MAX_SLOTS 20
#define EEPROM_SIZE 512

// ========== 165N pin definition  ==========
#define ES32_165N_load_pin     16
#define ES32_165N_dataIn_pin    5
#define ES32_165N_clockIn_pin  17

// ========== 595 pin definition ==========
#define ES32_595N_DATA_PIN     13
#define ES32_595N_CLOCK_PIN    27
#define ES32_595N_LATCH_PIN    14
#define ES32_595N_OE_PIN        4

// ========== EEPROM függvények ==========
void setupSlots();
void writeToSlot(uint8_t slot, uint16_t value);
uint16_t readFromSlot(uint8_t slot);
void clearSlots();
void commitChanges();

// ========== 165N input ==========
byte ES32_flipByte(byte c);
bool ES32_get_bit(uint8_t data, int bit_index);

// ========== 595 output ==========
extern uint8_t relay_state;            // 8 relé állapota (bit0..bit7)
//extern uint8_t display_digits[4];      // 4 karakter kódja (0..94)
//extern bool display_dots[4];           // tizedespontok a 4 pozícióhoz

//extern const uint8_t digit_masks[4];   // digit választó maszkok (aktív LOW)
extern const uint8_t esphome_char_map[95]; // forrás karaktertérkép (7 szegmens)
extern uint8_t char_map[95];           // átalakított (soros) karaktertérkép
extern uint8_t es32_digit_selects[4];
extern uint8_t es32_segments[4];

void ES32_setupCharMap();
void ES32_writeRegs();
void ES32_setRelay(uint8_t relayNumber, bool state);
void ES32_displayString(const uint8_t* text, uint8_t length);
#endif