#include "buzzer.h"
#include <esp_system.h>

// Persistent FreeRTOS Worker & Atomic State Control
static TaskHandle_t buzzerTaskHandle = NULL;
static portMUX_TYPE buzzerMux = portMUX_INITIALIZER_UNLOCKED;

static volatile bool stopRequested = false;
static volatile bool buzzerRunning = false;
static volatile uint32_t activeStartTimeMs = 0;
static volatile uint32_t activeDurationMs = 0;

static String pendingTarget = "NONE";
static uint32_t pendingDurationMs = 5000;
static String lastExecutedTarget = "NONE";

static void buzzerWorkerTask(void* parameter);

// Check if either manual stop was requested OR the overall sequence deadline expired
static inline bool shouldAbort() {
  if (stopRequested) return true;
  if (activeDurationMs > 0 && (millis() - activeStartTimeMs >= activeDurationMs)) {
    return true;
  }
  return false;
}

void silenceBuzzer() {
  noTone(PIN_BUZZER);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
}

// Interruptible millisecond delay that checks deadline & stop flag every 2ms
static bool waitInterruptible(uint32_t ms) {
  uint32_t start = millis();
  while (millis() - start < ms) {
    if (shouldAbort()) {
      silenceBuzzer();
      return false;
    }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
  return !shouldAbort();
}

uint32_t getRandomizedClassDurationMs(const String& target) {
  String t = target;
  t.toUpperCase();
  t.trim();

  if (t.indexOf("BIRD") >= 0 || t == "0") {
    return (uint32_t)random(3000, 6001);   // 3.0s - 6.0s
  }
  if (t.indexOf("SMALL") >= 0 || t == "RABBIT" || t == "RACCOON" || t == "FOX" || t == "1") {
    return (uint32_t)random(5000, 9001);   // 5.0s - 9.0s
  }
  if (t.indexOf("LARGE") >= 0 || t == "DEER" || t == "COW" || t == "BEAR" || t == "2") {
    return (uint32_t)random(8000, 14001);  // 8.0s - 14.0s
  }
  return (uint32_t)random(3500, 6001);     // Default / test burst
}

void setupBuzzer() {
  randomSeed(esp_random());
  silenceBuzzer();

  if (buzzerTaskHandle == NULL) {
    xTaskCreatePinnedToCore(
      buzzerWorkerTask,
      "BuzzerWorker",
      4096,
      NULL,
      2,
      &buzzerTaskHandle,
      0
    );
  }
  Serial.printf("[BUZZER] Zero-latency persistent worker initialized on GPIO %d\n", PIN_BUZZER);
}

bool isBuzzerActive() {
  return buzzerRunning;
}

String getLastTarget() {
  return lastExecutedTarget;
}

uint32_t getCurrentDurationMs() {
  return buzzerRunning ? activeDurationMs : 0;
}

uint32_t getRemainingDurationMs() {
  if (!buzzerRunning || activeDurationMs == 0) return 0;
  uint32_t elapsed = millis() - activeStartTimeMs;
  if (elapsed >= activeDurationMs) return 0;
  return activeDurationMs - elapsed;
}

void stopBuzzer() {
  stopRequested = true;
  buzzerRunning = false;
  activeDurationMs = 0;
  silenceBuzzer();
  Serial.println("[BUZZER] Deterrent immediately silenced.");
}

// ==========================================
// PREDATOR & ALARM SOUND PATTERNS
// ==========================================

void playPredatorClicking(int numClicks) {
  for (int i = 0; i < numClicks; i++) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    tone(PIN_BUZZER, 2000 + random(-60, 65));
    delay(3);
    silenceBuzzer();
    int interval = 24 + (int)(16.0 * sin(i * 0.28)) + random(-4, 7);
    if (interval < 8) interval = 8;
    if (!waitInterruptible((uint32_t)interval)) return;
  }
}

void playRaptorScreech(int sweepDelayMs, int tailCycles) {
  for (int f = 2780; f >= 1840; f -= 25) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    int jitter = (f % 50 == 0) ? random(70, 115) : -random(55, 95);
    tone(PIN_BUZZER, f + jitter);
    delay(sweepDelayMs);
  }
  for (int i = 0; i < tailCycles; i++) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    tone(PIN_BUZZER, 2080 + random(-30, 35));
    delay(random(5, 10));
    tone(PIN_BUZZER, 1950 + random(-30, 35));
    delay(random(5, 10));
  }
  silenceBuzzer();
}

void playStaccatoAlarm(int bursts, int onMs, int offMs) {
  for (int i = 0; i < bursts; i++) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    tone(PIN_BUZZER, 2000 + random(-40, 45));
    if (!waitInterruptible((uint32_t)onMs)) return;
    silenceBuzzer();
    if (!waitInterruptible((uint32_t)offMs)) return;
  }
}

void playHarshWarble(int durationMs) {
  uint32_t start = millis();
  while (millis() - start < (uint32_t)durationMs) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    tone(PIN_BUZZER, 1980 + random(-35, 35));
    if (!waitInterruptible((uint32_t)random(18, 34))) return;
    tone(PIN_BUZZER, 2130 + random(-35, 35));
    if (!waitInterruptible((uint32_t)random(18, 34))) return;
  }
  silenceBuzzer();
}

void playDualToneSiren(int cycles, int halfCycleMs) {
  for (int i = 0; i < cycles; i++) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    tone(PIN_BUZZER, 1950);
    if (!waitInterruptible((uint32_t)halfCycleMs)) return;
    tone(PIN_BUZZER, 2150);
    if (!waitInterruptible((uint32_t)halfCycleMs)) return;
  }
  silenceBuzzer();
}

// ==========================================
// PERSISTENT ZERO-LATENCY WORKER TASK
// ==========================================

static void buzzerWorkerTask(void* parameter) {
  for (;;) {
    // Sleep until woken instantaneously by triggerDeterrent()
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    String target;
    uint32_t maxDuration;

    portENTER_CRITICAL(&buzzerMux);
    target = pendingTarget;
    maxDuration = pendingDurationMs;
    stopRequested = false;
    activeStartTimeMs = millis();
    activeDurationMs = maxDuration;
    buzzerRunning = true;
    portEXIT_CRITICAL(&buzzerMux);

    target.toUpperCase();
    target.trim();
    lastExecutedTarget = target;

    Serial.printf("\n[BUZZER] >>> Executing Randomized Deterrent for: %s (Total Duration: %u ms) <<<\n",
                  target.c_str(), maxDuration);

    while (!shouldAbort()) {
      // 1. BIRD: RaptorScreech -> RaptorScreech -> StaccatoAlarm (with randomized sub-durations)
      if (target.indexOf("BIRD") >= 0 || target == "0") {
        playRaptorScreech(random(3, 7), random(8, 18));
        if (!waitInterruptible(random(60, 160))) break;
        playRaptorScreech(random(3, 7), random(8, 18));
        if (!waitInterruptible(random(60, 140))) break;
        playStaccatoAlarm(random(3, 9), random(45, 95), random(25, 65));
        if (!waitInterruptible(random(80, 180))) break;
      }
      // 2. SMALL MAMMAL: PredatorClicking -> RaptorScreech -> HarshWarble -> StaccatoAlarm
      else if (target.indexOf("SMALL") >= 0 || target == "RABBIT" || target == "RACCOON" || target == "FOX" || target == "1") {
        playPredatorClicking(random(10, 28));
        if (!waitInterruptible(random(50, 130))) break;
        playRaptorScreech(random(3, 6), random(10, 20));
        if (!waitInterruptible(random(60, 140))) break;
        playHarshWarble(random(500, 1400));
        if (!waitInterruptible(random(50, 120))) break;
        playStaccatoAlarm(random(4, 9), random(50, 90), random(30, 60));
        if (!waitInterruptible(random(80, 170))) break;
      }
      // 3. LARGE MAMMAL: PredatorClicking -> RaptorScreech -> StaccatoAlarm -> HarshWarble -> DualToneSiren
      else if (target.indexOf("LARGE") >= 0 || target == "DEER" || target == "COW" || target == "BEAR" || target == "2") {
        playPredatorClicking(random(12, 30));
        if (!waitInterruptible(random(40, 110))) break;
        playRaptorScreech(random(3, 6), random(10, 22));
        if (!waitInterruptible(random(50, 120))) break;
        playStaccatoAlarm(random(4, 10), random(55, 95), random(30, 65));
        if (!waitInterruptible(random(40, 100))) break;
        playHarshWarble(random(600, 1600));
        if (!waitInterruptible(random(40, 100))) break;
        playDualToneSiren(random(3, 7), random(90, 180));
        if (!waitInterruptible(random(80, 170))) break;
      }
      // 4. SOUND TEST / GENERIC ALARM
      else {
        playStaccatoAlarm(random(3, 7), random(50, 85), random(30, 55));
        if (!waitInterruptible(random(60, 120))) break;
        playDualToneSiren(random(2, 5), random(100, 150));
        if (!waitInterruptible(random(80, 150))) break;
      }
    }

    silenceBuzzer();
    uint32_t elapsed = millis() - activeStartTimeMs;
    buzzerRunning = false;
    activeDurationMs = 0;
    Serial.printf("[BUZZER] Sequence finished for: %s (%lu ms elapsed)\n\n", target.c_str(), elapsed);
  }
}

uint32_t triggerDeterrent(const String& target, uint32_t durationMs) {
  String t = target;
  t.toUpperCase();
  t.trim();

  if (t == "OFF" || t == "STOP" || t == "NONE" || t == "SAFE" || t == "3") {
    stopBuzzer();
    return 0;
  }

  uint32_t resolvedDuration = (durationMs > 0) ? durationMs : getRandomizedClassDurationMs(t);

  portENTER_CRITICAL(&buzzerMux);
  stopRequested = true; // Preempt any active tone loop immediately
  pendingTarget = t;
  pendingDurationMs = resolvedDuration;
  portEXIT_CRITICAL(&buzzerMux);

  if (buzzerTaskHandle != NULL) {
    xTaskNotifyGive(buzzerTaskHandle);
  }

  return resolvedDuration;
}
