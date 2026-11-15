#ifndef PUMP_H
#define PUMP_H

#include <Arduino.h>

// ==============================================================================
// WATER PUMP HARDWARE PIN
// ==============================================================================
// GPIO 18: Water Pump Relay / MOSFET Control Pin
// Active-HIGH (HIGH = Pump ON, LOW = Pump OFF, Default = LOW)
// ==============================================================================
const int PUMP_PIN = 18;

// Lifecycle & Control
void setupPump();
void silencePump();
uint32_t getRandomizedPumpDurationMs(const String& target);
uint32_t triggerPump(const String& target, uint32_t durationMs = 0);
void stopPump();

// Telemetry Getters
bool isPumpActive();
uint32_t getCurrentPumpDurationMs();
uint32_t getRemainingPumpDurationMs();

#endif // PUMP_H
