FUNCTION_BLOCK write7SegmentDisplay
VAR_INPUT
	InText : string := ----;
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
#include <BoardDriver_ES32A08.h>
void setup() {

}


void loop() {
    // Frissítsd a kijelzőt az aktuális szöveggel
  ES32_displayString(InText.body, InText.len);
//ES32_updateRegisters();
}

END_FUNCTION_BLOCK