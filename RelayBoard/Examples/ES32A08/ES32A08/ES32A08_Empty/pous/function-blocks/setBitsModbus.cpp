FUNCTION_BLOCK setBitsModbus
VAR_INPUT
	InBit0 : bool;
	InBit1 : bool;
	InBit2 : bool;
	InBit3 : bool;
	InBit4 : bool;
	InBit5 : bool;
	InBit6 : bool;
	InBit7 : bool;
	InBit8 : bool;
	InBit9 : bool;
	InBit10 : bool;
	InBit11 : bool;
	InBit12 : bool;
	InBit13 : bool;
	InBit14 : bool;
	InBit15 : bool;
END_VAR

VAR_OUTPUT
	OutValue : uint;
END_VAR
/* ================================================================
 *  C/C++ FUNCTION BLOCK
 *
 *  ---------------------------------------------------------------
 *  - This function block runs **in sync** with the PLC runtime.
 *  - The `setup()` function is called once when the block initializes.
 *  - The `loop()` function is called at every PLC scan cycle.
 *  - Block input and output variables declared in the variable table
 *    can be accessed directly by name in this C/C++ code.
 *
 *  This block executes as part of the main PLC process and follows
 *  the configured scan time in the Resources. Use it for real-time
 *  control logic, fast I/O operations, or any C-based algorithms.
 * ================================================================ */

#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

uint16_t setBitModbusValue(uint16_t number, uint8_t position, bool bitValue) {
  if (bitValue) {
    return number | (1 << position);   // bit = 1
  } else {
    return number & ~(1 << position);  // bit = 0
  }
}

// Called once when the block is initialized
void setup()
{

}

// Called at every PLC scan cycle
void loop()
{
setBitModbusValue(OutValue, 0, InBit0);
setBitModbusValue(OutValue, 1, InBit1);
setBitModbusValue(OutValue, 2, InBit2);
setBitModbusValue(OutValue, 3, InBit3);
setBitModbusValue(OutValue, 4, InBit4);
setBitModbusValue(OutValue, 5, InBit5);
setBitModbusValue(OutValue, 6, InBit6);
setBitModbusValue(OutValue, 7, InBit7);
setBitModbusValue(OutValue, 8, InBit8);
setBitModbusValue(OutValue, 9, InBit9);
setBitModbusValue(OutValue, 10, InBit10);
setBitModbusValue(OutValue, 11, InBit11);
setBitModbusValue(OutValue, 12, InBit12);
setBitModbusValue(OutValue, 13, InBit13);
setBitModbusValue(OutValue, 14, InBit14);
setBitModbusValue(OutValue, 15, InBit15);
}

END_FUNCTION_BLOCK