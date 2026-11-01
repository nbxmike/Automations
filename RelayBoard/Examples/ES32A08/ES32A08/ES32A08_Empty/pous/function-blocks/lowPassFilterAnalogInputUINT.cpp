FUNCTION_BLOCK lowPassFilterAnalogInputUINT
VAR_INPUT
	AnalogInputValue : uint;
END_VAR

VAR_OUTPUT
	AnalogInputFilteredValue : uint;
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

/*
Simítás mértéke	Kód (súlyozás)	Alfa	Hatás
nagyon erős	(sim*15 + uj*1)/16	0,06	nagyon lassú reagálás
erős	(sim*9 + uj*1)/10	0,1	közepes (ajánlott)
közepes	(sim*3 + uj*1)/4	0,25	gyorsabb, de még simít
gyenge	(sim*1 + uj*1)/2	0,5	kis simítás, majdnem nyers
*/


uint16_t idoAlapuSimitott(uint16_t uj) {
  static uint16_t sim = 0;
  static unsigned long elozoIdo = 0;
  static bool elso = true;
  unsigned long most = millis();
  
  if (elso) {
    sim = uj;
    elozoIdo = most;
    elso = false;
    return sim;
  }
  
  unsigned long dt = most - elozoIdo;
  if (dt > 100) dt = 100; // max 100 ms
  
  // Időállandó pl. 500 ms
  float alfa = (float)dt / 500.0;
  if (alfa > 1.0) alfa = 1.0;
  
  sim = sim * (1.0 - alfa) + uj * alfa;
  elozoIdo = most;
  return sim;
}

// Called once when the block is initialized
void setup()
{

}

// Called at every PLC scan cycle
void loop()
{
AnalogInputFilteredValue = idoAlapuSimitott(AnalogInputValue);
}

END_FUNCTION_BLOCK