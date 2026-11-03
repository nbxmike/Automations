FUNCTION_BLOCK rateLimiterAnalogInputUINT
VAR_INPUT
	AnalogInValue : uint;
END_VAR

VAR_OUTPUT
	AnalogOutValue : uint;
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

uint16_t rateLimit(uint16_t target) {
  static uint16_t output = 0;
  static unsigned long lastTime = 0;
  static bool first = true;
  
  if (first) {
    output = target;
    lastTime = millis();
    first = false;
    return output;
  }
  
  unsigned long now = millis();
  unsigned long dt = now - lastTime;
  if (dt > 100) dt = 100;
  
  const uint16_t maxRatePerSec = 2500; //minta sebesség
  uint16_t maxChange = (maxRatePerSec * dt) / 1000;
  
  int32_t diff = (int32_t)target - (int32_t)output;
  if (diff > 0) {
    int32_t step = (maxChange < diff) ? maxChange : diff;
    output += step;
  } else if (diff < 0) {
    int32_t step = (maxChange < -diff) ? maxChange : -diff;
    output -= step;
  }
  
  lastTime = now;
  return output;
}

// Called once when the block is initialized
void setup()
{

}

// Called at every PLC scan cycle
void loop()
{
AnalogOutValue = rateLimit(AnalogInValue);
}

END_FUNCTION_BLOCK