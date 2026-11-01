#include "BoardDriver_ES32A08.h"

// ========== EEPROM függvények ==========

// 1. Inicializing eprom system
void setupSlots() {
    EEPROM.begin(EEPROM_SIZE);
}

// 2. Write slot
void writeToSlot(uint8_t slot, uint16_t value) {
    if (slot >= MAX_SLOTS) return;
    int addr = slot * 2;
    uint8_t highByte = (value >> 8) & 0xFF;
    uint8_t lowByte = value & 0xFF;
    
    if (EEPROM.read(addr) != highByte || EEPROM.read(addr + 1) != lowByte) {
        EEPROM.write(addr, highByte);
        EEPROM.write(addr + 1, lowByte);
    }
}

// 3. Read slot
uint16_t readFromSlot(uint8_t slot) {
    if (slot >= MAX_SLOTS) return 0;
    int addr = slot * 2;
    return (EEPROM.read(addr) << 8) | EEPROM.read(addr + 1);
}

// 4. Clear all slots
void clearSlots() {
    for (int i = 0; i < MAX_SLOTS; i++) {
        writeToSlot(i, 0);
    }
    EEPROM.commit();
}

// Változások fizikai EEPROM-ba írása
void commitChanges() {
    EEPROM.commit();
}

// ========== 165N input ==========

byte ES32_flipByte(byte c){
  char r=0;
  for(byte i = 0; i < 8; i++){
    r <<= 1;
    r |= c & 1;
    c >>= 1;
  }
  return r;
}

bool ES32_get_bit(uint8_t data, int bit_index) {
    // Ellenőrizzük, hogy a bit_index érvényes tartományban van-e (0-7)
    if (bit_index < 0 || bit_index > 7) {
        return false; // Érvénytelen bit index esetén false-t adunk vissza
    }
    return (data >> bit_index) & 1;
}

// ========== 595 output ==========

uint8_t ES32_char_map[95];
uint8_t ES32_relay_state = 0;
//uint8_t display_digits[4] = {0,0,0,0};
//bool display_dots[4] = {false,false,false,false};
uint8_t es32_digit_selects[4];
uint8_t es32_segments[4];

// Digit választó maszkok (aktív LOW)
const uint8_t ES32_digit_masks[4] = {
  0b11111110,  // ezres (bit0)
  0b11111101,  // százas (bit1)
  0b11111011,  // tízes (bit2)
  0b11110111   // egyes (bit3)
};

const uint8_t ES32_esphome_char_map[95] = {
  0b00000000,            // ' '
  0b10110000,            // '!'
  0b00100010,            // '"'
  0b00000000,            // '#'
  0b00000000,            // '$'
  0b01001001,            // '%'
  0b00000000,            // '&'
  0b00000010,            // '''
  0b01001110,            // '('
  0b01111000,            // ')'
  0b01000000,            // '*'
  0b00000000,            // '+'
  0b00010000,            // ','
  0b00000001,            // '-'
  0b10000000,            // '.'
  0b00000000,            // '/'
  0b01111110,            // '0'
  0b00110000,            // '1'
  0b01101101,            // '2'
  0b01111001,            // '3'
  0b00110011,            // '4'
  0b01011011,            // '5'
  0b01011111,            // '6'
  0b01110000,            // '7'
  0b01111111,            // '8'
  0b01111011,            // '9'
  0b01001000,            // ':'
  0b01011000,            // ';'
  0b00000000,            // '<'
  0b00001001,            // '='
  0b00000000,            // '>'
  0b01100101,            // '?'
  0b01101111,            // '@'
  0b01110111,            // 'A'
  0b00011111,            // 'B'
  0b01001110,            // 'C'
  0b00111101,            // 'D'
  0b01001111,            // 'E'
  0b01000111,            // 'F'
  0b01011110,            // 'G'
  0b00110111,            // 'H'
  0b00110000,            // 'I'
  0b00111100,            // 'J'
  0b00000000,            // 'K'
  0b00001110,            // 'L'
  0b00000000,            // 'M'
  0b00010101,            // 'N'
  0b01111110,            // 'O'
  0b01100111,            // 'P'
  0b11111110,            // 'Q'
  0b00000101,            // 'R'
  0b01011011,            // 'S'
  0b00000111,            // 'T'
  0b00111110,            // 'U'
  0b00111110,            // 'V'
  0b00111111,            // 'W'
  0b00000000,            // 'X'
  0b00100111,            // 'Y'
  0b01101101,            // 'Z'
  0b01001110,            // '['
  0b00000000,            // '\'
  0b01111000,            // ']'
  0b00000000,            // '^'
  0b00001000,            // '_'
  0b00100000,            // '`'
  0b01110111,            // 'a'
  0b00011111,            // 'b'
  0b00001101,            // 'c'
  0b00111101,            // 'd'
  0b01001111,            // 'e'
  0b01000111,            // 'f'
  0b01011110,            // 'g'
  0b00010111,            // 'h'
  0b00010000,            // 'i'
  0b00111100,            // 'j'
  0b00000000,            // 'k'
  0b00001110,            // 'l'
  0b00000000,            // 'm'
  0b00010101,            // 'n'
  0b00011101,            // 'o'
  0b01100111,            // 'p'
  0b00000000,            // 'q'
  0b00000101,            // 'r'
  0b01011011,            // 's'
  0b00000111,            // 't'
  0b00011100,            // 'u'
  0b00011100,            // 'v'
  0b00000000,            // 'w'
  0b00000000,            // 'x'
  0b00100111,            // 'y'
  0b00000000,            // 'z'
  0b00110001,            // '{'
  0b00000110,            // '|'
  0b00000111,            // '}'
  0b01100011             // '~'
};

void ES32_setRelay(uint8_t relayNumber, bool state) {
    if (relayNumber >= 1 && relayNumber <= 8) {
        uint8_t bit = 1 << (relayNumber - 1);
        if (state) ES32_relay_state |= bit;
        else ES32_relay_state &= ~bit;
    }
}

void ES32_setupCharMap() {
  for (int i = 0; i < 95; i++) {
    uint8_t src = ES32_esphome_char_map[i];
    uint8_t dst = 0;
    dst |= ((src >> 6) & 1) << 0;   // A -> a
    dst |= ((src >> 5) & 1) << 1;   // B -> b
    dst |= ((src >> 4) & 1) << 2;   // C -> c
    dst |= ((src >> 3) & 1) << 3;   // D -> d
    dst |= ((src >> 2) & 1) << 4;   // E -> e
    dst |= ((src >> 1) & 1) << 5;   // F -> f
    dst |= ((src >> 0) & 1) << 6;   // G -> g
    dst |= ((src >> 7) & 1) << 7;   // DP -> dp
    ES32_char_map[i] = dst;
  }
}

void ES32_writeRegs() {
    for (int i = 0; i < 4; i++) {
       digitalWrite(ES32_595N_LATCH_PIN, LOW); 
       shiftOut(ES32_595N_DATA_PIN, ES32_595N_CLOCK_PIN, MSBFIRST, ES32_relay_state);
       shiftOut(ES32_595N_DATA_PIN, ES32_595N_CLOCK_PIN, MSBFIRST, es32_digit_selects[i]);
       shiftOut(ES32_595N_DATA_PIN, ES32_595N_CLOCK_PIN, MSBFIRST, es32_segments[i]);
       digitalWrite(ES32_595N_LATCH_PIN, HIGH);
       delay(5);
    }
}

void ES32_displayString(const uint8_t* text, uint8_t length) {
    String str = String((const char*)text, length);
    
    // 1. Karakterek és pontok feldolgozása
    char chars[4];
    bool dots[4] = {false};
    int charCount = 0;
    int len = str.length();

    for (int i = 0; i < len && charCount < 4; i++) {
        char c = str[i];
        if (c == '.') {
            if (charCount > 0) dots[charCount-1] = true;
        } else {
            chars[charCount] = c;
            charCount++;
        }
    }

    // 2. Jobbra igazítás és a globális tömbök feltöltése
    int offset = 4 - charCount;
    for (int i = 0; i < 4; i++) {
        char ch;
        bool dot;
        if (i < offset) {
            ch = ' ';
            dot = false;
        } else {
            int idx = i - offset;
            ch = chars[idx];
            dot = dots[idx];
        }
        uint8_t mapIdx = (ch >= 32 && ch <= 126) ? (ch - 32) : 0;
        es32_segments[i] = ES32_char_map[mapIdx];
        if (dot) es32_segments[i] |= 0b10000000;
        es32_digit_selects[i] = ES32_digit_masks[i];
    }
}