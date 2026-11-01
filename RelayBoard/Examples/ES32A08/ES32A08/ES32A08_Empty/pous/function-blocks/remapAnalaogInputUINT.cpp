FUNCTION_BLOCK remapAnalaogInputUINT
VAR_INPUT
	UintIn : uint;
	UintInMin : uint;
	UintInMax : uint;
	RemapInMin : uint;
	RemapInMax : uint;
END_VAR

VAR_OUTPUT
	RemappedOUT : uint;
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
#include <stddef.h>   // NULL, size_t stb. (nem feltétlenül szükséges)
#include <float.h>    // lebegőpontos konstansokhoz
// unsigned int (platformfüggő)
unsigned int remap_uint(unsigned int x, unsigned int in_min, unsigned int in_max,
                        unsigned int out_min, unsigned int out_max) {
    if (in_min == in_max) return (out_min + out_max) / 2;
    uint64_t temp = (uint64_t)(x - in_min) * (out_max - out_min);
    uint64_t result = temp / (in_max - in_min) + out_min;
    return (unsigned int)result;
}
// Called once when the block is initialized
void setup()
{

}

// Called at every PLC scan cycle
void loop()
{
RemappedOUT = remap_uint(UintIn, UintInMin, UintInMax, RemapInMin, RemapInMax);


}

END_FUNCTION_BLOCK