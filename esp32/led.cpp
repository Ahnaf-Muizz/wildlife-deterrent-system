#include "led.h"
#include <esp_system.h>

// Persistent FreeRTOS Worker & Atomic State Control for 3W COB LED MOSFET
static TaskHandle_t ledTaskHandle = NULL;
static portMUX_TYPE ledMux = portMUX_INITIALIZER_UNLOCKED;

static volatile bool stopLedRequested = false;
static volatile bool ledRunning = false;
static volatile bool ledOutputState = false;
static volatile uint32_t ledStartTimeMs = 0;
static volatile uint32_t ledDurationMs = 0;
static volatile uint32_t ledCommandGen = 0;

static char pendingLedTargetBuf[32] = "NONE";
static uint32_t pendingLedDurationMs = 0;

static void ledWorkerTask(void* parameter);

void setLedOutput(bool on) {
  ledOutputState = on;
  const bool gpioLevel = MOSFET_ACTIVE_LOW ? !on : on;
  digitalWrite(LED_PIN, gpioLevel ? HIGH : LOW);
}

void silenceLed() {
  pinMode(LED_PIN, OUTPUT);
  setLedOutput(false);
}

// Check if manual stop was requested OR the randomized activation duration expired
static inline bool shouldAbortLed() {
  if (stopLedRequested) return true;
  if (ledDurationMs > 0 && (millis() - ledStartTimeMs >= ledDurationMs)) {
    return true;
  }
  return false;
}

// Interruptible millisecond delay that checks deadline & stop flag every 2ms
static bool waitLedInterruptible(uint32_t ms) {
  uint32_t start = millis();
  while (millis() - start < ms) {
    if (shouldAbortLed()) {
      silenceLed();
      return false;
    }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
  return !shouldAbortLed();
}

bool isLedTargetAllowed(const String& target) {
  String t = target;
  t.toUpperCase();
  t.trim();

  if (t.length() == 0 || t == "OFF" || t == "STOP" || t == "NONE" || t == "SAFE" || t == "HUMAN" || t == "3") {
    return false;
  }
  if (t.indexOf("WATER") >= 0 || t.indexOf("PUMP") >= 0 ||
      t.indexOf("SOUND") >= 0 || t.indexOf("BUZZER") >= 0) {
    return false;
  }
  if (t == "LIGHT_TEST_SMALL" || t == "LED_TEST_SMALL") {
    return true;
  }
  if (t.indexOf("BIRD") >= 0 || t == "0" || t == "LIGHT_TEST_BIRD" ||
      t.indexOf("LARGE") >= 0 || t == "DEER" || t == "COYOTE" ||
      t == "COW" || t == "BEAR" || t == "2" || t == "LIGHT_TEST_LARGE") {
    return true;
  }
  if (t.indexOf("SMALL") >= 0 || t == "SQUIRREL" || t == "DOG" || t == "CAT" ||
      t == "RABBIT" || t == "RACCOON" || t == "FOX" || t == "1") {
    return false;
  }
  if (t == "LIGHT" || t == "LED" || t == "LIGHT_TEST" || t == "LED_TEST" ||
      t.startsWith("LIGHT_TEST_") || t.startsWith("LED_TEST_")) {
    return true;
  }
  return false;
}

uint32_t getRandomizedLedDurationMs(const String& target) {
  String t = target;
  t.toUpperCase();
  t.trim();

  if (!isLedTargetAllowed(t)) {
    return 0;
  }

  // Manual tier-specific Light tests
  if (t == "LIGHT_TEST_SMALL" || t == "LED_TEST_SMALL") {
    return (uint32_t)random(5000, 9001);   // 5.0s - 9.0s
  }

  // Class 0 (BIRD: Sound + Light) or LIGHT_TEST_BIRD -> Randomized 3.0s - 6.0s
  if (t.indexOf("BIRD") >= 0 || t == "0" || t == "LIGHT_TEST_BIRD") {
    return (uint32_t)random(3000, 6001);   // 3000ms - 6000ms
  }

  // Class 2 (LARGE MAMMAL: Sound + Light + Water) or LIGHT_TEST_LARGE -> Randomized 8.0s - 14.0s
  if (t.indexOf("LARGE") >= 0 || t == "DEER" || t == "COYOTE" ||
      t == "COW" || t == "BEAR" || t == "2" || t == "LIGHT_TEST_LARGE") {
    return (uint32_t)random(8000, 14001);  // 8000ms - 14000ms
  }

  // Standalone LED Flash Test (LIGHT_TEST / LED_TEST / LIGHT / LED) -> Randomized 3.5s - 7.5s
  return (uint32_t)random(3500, 7501);
}

void setupLed() {
  randomSeed(esp_random());
  silenceLed();

  if (ledTaskHandle == NULL) {
    xTaskCreatePinnedToCore(
      ledWorkerTask,
      "LedWorker",
      3072,
      NULL,
      1,
      &ledTaskHandle,
      1
    );
  }
  Serial.printf("[LED] Zero-latency IRLZ44PBF MOSFET strobe initialized on GPIO %d (Core 1, Active: %s, Default: OFF)\n",
                LED_PIN, MOSFET_ACTIVE_LOW ? "LOW" : "HIGH");
}

bool isLedActive() {
  return ledRunning;
}

uint32_t getCurrentLedDurationMs() {
  return ledRunning ? ledDurationMs : 0;
}

uint32_t getRemainingLedDurationMs() {
  if (!ledRunning || ledDurationMs == 0) return 0;
  uint32_t elapsed = millis() - ledStartTimeMs;
  if (elapsed >= ledDurationMs) return 0;
  return ledDurationMs - elapsed;
}

void stopLed() {
  portENTER_CRITICAL(&ledMux);
  stopLedRequested = true;
  pendingLedDurationMs = 0;
  ledCommandGen++;
  ledRunning = false;
  ledDurationMs = 0;
  portEXIT_CRITICAL(&ledMux);
  silenceLed();
  Serial.printf("[LED] LED strobe immediately turned OFF (GPIO %d -> %s).\n",
                LED_PIN, MOSFET_ACTIVE_LOW ? "HIGH" : "LOW");
}

// ==========================================
// PERSISTENT ZERO-LATENCY LED STROBE WORKER
// ==========================================
static void ledWorkerTask(void* parameter) {
  for (;;) {
    // Sleep until woken instantaneously by triggerLed()
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    char targetBuf[32];
    uint32_t onDurationMs = 0;
    uint32_t myGen = 0;

    portENTER_CRITICAL(&ledMux);
    myGen = ledCommandGen;
    strlcpy(targetBuf, pendingLedTargetBuf, sizeof(targetBuf));
    onDurationMs = pendingLedDurationMs;
    pendingLedDurationMs = 0;
    if (onDurationMs > 0) {
      stopLedRequested = false;
      ledStartTimeMs = millis();
      ledDurationMs = onDurationMs;
      ledRunning = true;
    } else {
      ledRunning = false;
      ledDurationMs = 0;
    }
    portEXIT_CRITICAL(&ledMux);

    if (onDurationMs == 0) {
      silenceLed();
      continue;
    }

    String target(targetBuf);
    target.toUpperCase();
    target.trim();
    const bool isLarge = (target.indexOf("LARGE") >= 0 || target == "2");

    Serial.printf("[LED] >>> Executing Randomized Flash Sequence on GPIO %d for '%s' (Duration: %u ms) <<<\n",
                  LED_PIN, target.c_str(), onDurationMs);

    // Randomize flash durations & inter-flash dark intervals throughout the deterrent window
    while (!shouldAbortLed()) {
      // 1. Rapid randomized strobe burst to prevent wildlife habituation
      int burstCount = random(3, 8);
      for (int i = 0; i < burstCount; i++) {
        if (shouldAbortLed()) break;
        uint32_t onMs = isLarge ? (uint32_t)random(35, 160) : (uint32_t)random(55, 220);
        setLedOutput(true);
        if (!waitLedInterruptible(onMs)) break;

        uint32_t offMs = isLarge ? (uint32_t)random(30, 140) : (uint32_t)random(50, 200);
        setLedOutput(false);
        if (!waitLedInterruptible(offMs)) break;
      }

      if (shouldAbortLed()) break;

      // 2. High-intensity blinding hold pulse(s) & irregular inter-burst pause
      int holdCount = random(1, 3);
      for (int h = 0; h < holdCount; h++) {
        if (shouldAbortLed()) break;
        uint32_t holdOnMs = (uint32_t)random(180, 420);
        setLedOutput(true);
        if (!waitLedInterruptible(holdOnMs)) break;

        uint32_t holdOffMs = (uint32_t)random(80, 260);
        setLedOutput(false);
        if (!waitLedInterruptible(holdOffMs)) break;
      }
    }

    silenceLed();
    uint32_t elapsed = millis() - ledStartTimeMs;
    portENTER_CRITICAL(&ledMux);
    if (ledCommandGen == myGen) {
      ledRunning = false;
      ledDurationMs = 0;
    }
    portEXIT_CRITICAL(&ledMux);
    Serial.printf("[LED] Strobe sequence finished on GPIO %d (%lu ms elapsed)\n", LED_PIN, elapsed);
  }
}

uint32_t triggerLed(const String& target, uint32_t durationMs) {
  String t = target;
  t.toUpperCase();
  t.trim();

  // Safety Override (SAFE / HUMAN / STOP / OFF)
  if (t == "OFF" || t == "STOP" || t == "NONE" || t == "SAFE" || t == "HUMAN" || t == "3") {
    stopLed();
    return 0;
  }

  // Enforce strict allowlist BEFORE applying caller-provided durationMs
  if (!isLedTargetAllowed(t)) {
    stopLed();
    return 0;
  }

  // Respect caller-provided durationMs when supplied (so LED shuts off at the same time as Buzzer/Pump),
  // while keeping flash bursts & intervals randomized throughout the window.
  uint32_t resolvedDuration = (durationMs > 0)
                                ? durationMs
                                : getRandomizedLedDurationMs(t);

  if (resolvedDuration == 0) {
    stopLed();
    return 0;
  }

  portENTER_CRITICAL(&ledMux);
  stopLedRequested = true; // Preempt any active flash loop immediately
  strlcpy(pendingLedTargetBuf, t.c_str(), sizeof(pendingLedTargetBuf));
  pendingLedDurationMs = resolvedDuration;
  ledCommandGen++;
  portEXIT_CRITICAL(&ledMux);

  if (ledTaskHandle != NULL) {
    xTaskNotifyGive(ledTaskHandle);
  }

  return resolvedDuration;
}
