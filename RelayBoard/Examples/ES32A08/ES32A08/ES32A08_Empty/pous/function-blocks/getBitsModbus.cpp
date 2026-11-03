FUNCTION_BLOCK getBitsModbus
VAR_INPUT
	InValue : uint;
END_VAR

VAR_OUTPUT
	OutBit0 : bool;
	OutBit1 : bool;
	OutBit2 : bool;
	OutBit3 : bool;
	OutBit4 : bool;
	OutBit5 : bool;
	OutBit6 : bool;
	OutBit7 : bool;
	OutBit8 : bool;
	OutBit9 : bool;
	OutBit10 : bool;
	OutBit11 : bool;
	OutBit12 : bool;
	OutBit13 : bool;
	OutBit14 : bool;
	OutBit15 : bool;
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

bool getBitModbusValue(uint16_t number, uint8_t position) {
  // position: 0 = legkisebb helyiértékű bit (LSB), 15 = legnagyobb (MSB)
  return (number >> position) & 1;
}
// Called once when the block is initialized
void setup()
{

}

// Called at every PLC scan cycle
void loop()
{
OutBit0 = getBitModbusValue(InValue, 0);
OutBit1 = getBitModbusValue(InValue, 1);
OutBit2 = getBitModbusValue(InValue, 2);
OutBit3 = getBitModbusValue(InValue, 3);
OutBit4 = getBitModbusValue(InValue, 4);
OutBit5 = getBitModbusValue(InValue, 5);
OutBit6 = getBitModbusValue(InValue, 6);
OutBit7 = getBitModbusValue(InValue, 7);
OutBit8 = getBitModbusValue(InValue, 8);
OutBit9 = getBitModbusValue(InValue, 9);
OutBit10 = getBitModbusValue(InValue, 10);
OutBit11 = getBitModbusValue(InValue, 11);
OutBit12 = getBitModbusValue(InValue, 12);
OutBit13 = getBitModbusValue(InValue, 13);
OutBit14 = getBitModbusValue(InValue, 14);
OutBit15 = getBitModbusValue(InValue, 15);
}

END_FUNCTION_BLOCK