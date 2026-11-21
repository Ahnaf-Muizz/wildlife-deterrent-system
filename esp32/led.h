#ifndef LED_H
#define LED_H

#include <Arduino.h>

// ==============================================================================
// LED / IRLZ44PBF MOSFET DETERRENT HARDWARE PIN
// ==============================================================================
// GPIO 16: Controls the IRLZ44PBF N-channel MOSFET gate for the 3W COB LED
// false = GPIO HIGH turns MOSFET ON (normal low-side switching, Default OFF/LOW)
// true  = GPIO LOW turns MOSFET ON (inverted control)
// ==============================================================================
const int LED_PIN = 16;
static constexpr uint8_t LIGHT_PIN = 16;
static constexpr bool MOSFET_ACTIVE_LOW = false;

// Lifecycle & Control
void setupLed();
void silenceLed();
void setLedOutput(bool on);
uint32_t getRandomizedLedDurationMs(const String& target);
bool isLedTargetAllowed(const String& target);
uint32_t triggerLed(const String& target, uint32_t durationMs = 0);
void stopLed();

// Telemetry Getters
bool isLedActive();
uint32_t getCurrentLedDurationMs();
uint32_t getRemainingLedDurationMs();

#endif // LED_H
