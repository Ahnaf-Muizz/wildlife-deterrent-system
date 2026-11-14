#ifndef BUZZER_H
#define BUZZER_H

#include <Arduino.h>

// ==============================================================================
// BUZZER HARDWARE PIN
// ==============================================================================
// GPIO 17: Pin 10 on the left header of ESP32-S3-DevKitC-1.
// Pure digital pin, completely free from Touch sensor noise.
// ==============================================================================
const uint8_t PIN_BUZZER = 17;

// Lifecycle & Control
void setupBuzzer();
void silenceBuzzer();
uint32_t getRandomizedClassDurationMs(const String& target);
uint32_t triggerDeterrent(const String& target, uint32_t durationMs = 0);
void stopBuzzer();
bool isBuzzerActive();
String getLastTarget();
uint32_t getCurrentDurationMs();
uint32_t getRemainingDurationMs();

// Individual Sound Primitives (2000 Hz Resonant Peak with Randomized Timing)
void playPredatorClicking(int numClicks = 20);
void playRaptorScreech(int sweepDelayMs = 4, int tailCycles = 12);
void playStaccatoAlarm(int bursts = 6, int onMs = 70, int offMs = 40);
void playHarshWarble(int durationMs = 1000);
void playDualToneSiren(int cycles = 5, int halfCycleMs = 130);

#endif // BUZZER_H
