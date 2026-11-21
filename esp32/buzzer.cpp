#include "buzzer.h"
#include <esp_system.h>

// Persistent FreeRTOS Worker & Atomic State Control for Sound Buzzer
static TaskHandle_t buzzerTaskHandle = NULL;
static portMUX_TYPE buzzerMux = portMUX_INITIALIZER_UNLOCKED;

static volatile bool stopRequested = false;
static volatile bool buzzerRunning = false;
static volatile uint32_t activeStartTimeMs = 0;
static volatile uint32_t activeDurationMs = 0;
static volatile uint32_t buzzerCommandGen = 0;

static char pendingTargetBuf[32] = "NONE";
static uint32_t pendingDurationMs = 0;
static char lastExecutedTargetBuf[32] = "NONE";

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
  ledcWriteTone(PIN_BUZZER, 0);
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
  if (t.indexOf("SMALL") >= 0 || t == "SQUIRREL" || t == "DOG" || t == "CAT" ||
      t == "RABBIT" || t == "RACCOON" || t == "FOX" || t == "1") {
    return (uint32_t)random(5000, 9001);   // 5.0s - 9.0s
  }
  if (t.indexOf("LARGE") >= 0 || t == "DEER" || t == "COYOTE" ||
      t == "COW" || t == "BEAR" || t == "2") {
    return (uint32_t)random(8000, 14001);  // 8.0s - 14.0s
  }
  return (uint32_t)random(3500, 6001);     // Default / test burst
}

void setupBuzzer() {
  randomSeed(esp_random());
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
  ledcAttach(PIN_BUZZER, 2000, 10);
  ledcWriteTone(PIN_BUZZER, 0);

  if (buzzerTaskHandle == NULL) {
    xTaskCreatePinnedToCore(
      buzzerWorkerTask,
      "BuzzerWorker",
      4096,
      NULL,
      1,
      &buzzerTaskHandle,
      1
    );
  }
  Serial.printf("[BUZZER] Zero-latency persistent worker initialized on GPIO %d (Core 1)\n", PIN_BUZZER);
}

bool isBuzzerActive() {
  return buzzerRunning;
}

String getLastTarget() {
  char buf[32];
  portENTER_CRITICAL(&buzzerMux);
  strlcpy(buf, lastExecutedTargetBuf, sizeof(buf));
  portEXIT_CRITICAL(&buzzerMux);
  return String(buf);
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

bool isBuzzerTargetAllowed(const String& target) {
  String t = target;
  t.toUpperCase();
  t.trim();

  if (t.length() == 0 || t == "OFF" || t == "STOP" || t == "NONE" || t == "SAFE" || t == "HUMAN" || t == "3") {
    return false;
  }
  if (t.indexOf("WATER") >= 0 || t.indexOf("PUMP") >= 0 ||
      t.indexOf("LIGHT") >= 0 || t.indexOf("LED") >= 0) {
    return false;
  }
  if (t == "SOUND" || t == "BUZZER" || t == "SOUND_TEST" || t == "BUZZER_TEST" ||
      t.startsWith("SOUND_TEST_") || t.startsWith("BUZZER_TEST_")) {
    return true;
  }
  if (t.indexOf("BIRD") >= 0 || t == "0" ||
      t.indexOf("SMALL") >= 0 || t == "SQUIRREL" || t == "DOG" || t == "CAT" ||
      t == "RABBIT" || t == "RACCOON" || t == "FOX" || t == "1" ||
      t.indexOf("LARGE") >= 0 || t == "DEER" || t == "COYOTE" ||
      t == "COW" || t == "BEAR" || t == "2") {
    return true;
  }
  return false;
}

void stopBuzzer() {
  portENTER_CRITICAL(&buzzerMux);
  stopRequested = true;
  pendingDurationMs = 0;
  buzzerCommandGen++;
  buzzerRunning = false;
  activeDurationMs = 0;
  portEXIT_CRITICAL(&buzzerMux);
  silenceBuzzer();
  Serial.println("[BUZZER] Sound deterrent immediately silenced.");
}

// ==========================================
// PREDATOR & ALARM SOUND PATTERNS
// ==========================================

void playPredatorClicking(int numClicks) {
  for (int i = 0; i < numClicks; i++) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    ledcWriteTone(PIN_BUZZER, (uint32_t)(2000 + random(-60, 65)));
    if (!waitInterruptible(3)) return;
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
    ledcWriteTone(PIN_BUZZER, (uint32_t)max(400, f + jitter));
    if (!waitInterruptible((uint32_t)max(1, sweepDelayMs))) return;
  }
  for (int i = 0; i < tailCycles; i++) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    ledcWriteTone(PIN_BUZZER, (uint32_t)(2080 + random(-30, 35)));
    if (!waitInterruptible((uint32_t)random(5, 10))) return;
    ledcWriteTone(PIN_BUZZER, (uint32_t)(1950 + random(-30, 35)));
    if (!waitInterruptible((uint32_t)random(5, 10))) return;
  }
  silenceBuzzer();
}

void playStaccatoAlarm(int bursts, int onMs, int offMs) {
  for (int i = 0; i < bursts; i++) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    ledcWriteTone(PIN_BUZZER, (uint32_t)(2000 + random(-40, 45)));
    if (!waitInterruptible((uint32_t)onMs)) return;
    silenceBuzzer();
    if (!waitInterruptible((uint32_t)offMs)) return;
  }
}

void playHarshWarble(int durationMs) {
  uint32_t start = millis();
  while (millis() - start < (uint32_t)durationMs) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    ledcWriteTone(PIN_BUZZER, (uint32_t)(1980 + random(-35, 35)));
    if (!waitInterruptible((uint32_t)random(18, 34))) return;
    ledcWriteTone(PIN_BUZZER, (uint32_t)(2130 + random(-35, 35)));
    if (!waitInterruptible((uint32_t)random(18, 34))) return;
  }
  silenceBuzzer();
}

void playDualToneSiren(int cycles, int halfCycleMs) {
  for (int i = 0; i < cycles; i++) {
    if (shouldAbort()) { silenceBuzzer(); return; }
    ledcWriteTone(PIN_BUZZER, 1950);
    if (!waitInterruptible((uint32_t)halfCycleMs)) return;
    ledcWriteTone(PIN_BUZZER, 2150);
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

    char targetBuf[32];
    uint32_t maxDuration = 0;
    uint32_t myGen = 0;

    portENTER_CRITICAL(&buzzerMux);
    myGen = buzzerCommandGen;
    strlcpy(targetBuf, pendingTargetBuf, sizeof(targetBuf));
    maxDuration = pendingDurationMs;
    pendingDurationMs = 0;
    if (maxDuration > 0) {
      stopRequested = false;
      activeStartTimeMs = millis();
      activeDurationMs = maxDuration;
      buzzerRunning = true;
      strlcpy(lastExecutedTargetBuf, targetBuf, sizeof(lastExecutedTargetBuf));
    } else {
      buzzerRunning = false;
      activeDurationMs = 0;
    }
    portEXIT_CRITICAL(&buzzerMux);

    if (maxDuration == 0) {
      silenceBuzzer();
      continue;
    }

    String target(targetBuf);
    target.toUpperCase();
    target.trim();

    Serial.printf("\n[BUZZER] >>> Executing Randomized Sound Deterrent for: %s (Duration: %u ms) <<<\n",
                  target.c_str(), maxDuration);

    while (!shouldAbort()) {
      // 1. BIRD (or SOUND_TEST_BIRD): RaptorScreech -> RaptorScreech -> StaccatoAlarm
      if (target.indexOf("BIRD") >= 0 || target == "0") {
        playRaptorScreech(random(3, 7), random(8, 18));
        if (!waitInterruptible(random(60, 160))) break;
        playRaptorScreech(random(3, 7), random(8, 18));
        if (!waitInterruptible(random(60, 140))) break;
        playStaccatoAlarm(random(3, 9), random(45, 95), random(25, 65));
        if (!waitInterruptible(random(80, 180))) break;
      }
      // 2. SMALL MAMMAL (or SOUND_TEST_SMALL): PredatorClicking -> RaptorScreech -> HarshWarble -> StaccatoAlarm
      else if (target.indexOf("SMALL") >= 0 || target == "SQUIRREL" || target == "DOG" || target == "CAT" ||
               target == "RABBIT" || target == "RACCOON" || target == "FOX" || target == "1") {
        playPredatorClicking(random(10, 28));
        if (!waitInterruptible(random(50, 130))) break;
        playRaptorScreech(random(3, 6), random(10, 20));
        if (!waitInterruptible(random(60, 140))) break;
        playHarshWarble(random(500, 1400));
        if (!waitInterruptible(random(50, 120))) break;
        playStaccatoAlarm(random(4, 9), random(50, 90), random(30, 60));
        if (!waitInterruptible(random(80, 170))) break;
      }
      // 3. LARGE MAMMAL (or SOUND_TEST_LARGE): PredatorClicking -> RaptorScreech -> StaccatoAlarm -> HarshWarble -> DualToneSiren
      else if (target.indexOf("LARGE") >= 0 || target == "DEER" || target == "COYOTE" ||
               target == "COW" || target == "BEAR" || target == "2") {
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
    portENTER_CRITICAL(&buzzerMux);
    if (buzzerCommandGen == myGen) {
      buzzerRunning = false;
      activeDurationMs = 0;
    }
    portEXIT_CRITICAL(&buzzerMux);
    Serial.printf("[BUZZER] Sequence finished for: %s (%lu ms elapsed)\n\n", target.c_str(), elapsed);
  }
}

uint32_t triggerDeterrent(const String& target, uint32_t durationMs) {
  String t = target;
  t.toUpperCase();
  t.trim();

  if (t == "OFF" || t == "STOP" || t == "NONE" || t == "SAFE" || t == "HUMAN" || t == "3") {
    stopBuzzer();
    return 0;
  }

  if (!isBuzzerTargetAllowed(t)) {
    return 0;
  }

  uint32_t resolvedDuration = (durationMs > 0) ? durationMs : getRandomizedClassDurationMs(t);
  if (resolvedDuration == 0) {
    return 0;
  }

  portENTER_CRITICAL(&buzzerMux);
  stopRequested = true; // Preempt any active tone loop immediately
  strlcpy(pendingTargetBuf, t.c_str(), sizeof(pendingTargetBuf));
  pendingDurationMs = resolvedDuration;
  buzzerCommandGen++;
  portEXIT_CRITICAL(&buzzerMux);

  if (buzzerTaskHandle != NULL) {
    xTaskNotifyGive(buzzerTaskHandle);
  }

  return resolvedDuration;
}
