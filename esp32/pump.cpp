#include "pump.h"
#include <esp_system.h>

// Persistent FreeRTOS Worker & Atomic State Control for Water Pump
static TaskHandle_t pumpTaskHandle = NULL;
static portMUX_TYPE pumpMux = portMUX_INITIALIZER_UNLOCKED;

static volatile bool stopPumpRequested = false;
static volatile bool pumpRunning = false;
static volatile uint32_t pumpStartTimeMs = 0;
static volatile uint32_t pumpDurationMs = 0;
static volatile uint32_t pumpCommandGen = 0;
static uint32_t pendingPumpDurationMs = 0;

static void pumpWorkerTask(void* parameter);

// Check if manual stop was requested OR the randomized activation duration expired
static inline bool shouldAbortPump() {
  if (stopPumpRequested) return true;
  if (pumpDurationMs > 0 && (millis() - pumpStartTimeMs >= pumpDurationMs)) {
    return true;
  }
  return false;
}

void silencePump() {
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW); // Default to off
}

// Interruptible millisecond delay that checks deadline & stop flag every 2ms
static bool waitPumpInterruptible(uint32_t ms) {
  uint32_t start = millis();
  while (millis() - start < ms) {
    if (shouldAbortPump()) {
      silencePump();
      return false;
    }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
  return !shouldAbortPump();
}

bool isPumpTargetAllowed(const String& target) {
  String t = target;
  t.toUpperCase();
  t.trim();

  if (t.length() == 0 || t == "OFF" || t == "STOP" || t == "NONE" || t == "SAFE" || t == "HUMAN" || t == "3") {
    return false;
  }
  if (t.indexOf("BIRD") >= 0 || t == "0" ||
      t.indexOf("SOUND") >= 0 || t.indexOf("BUZZER") >= 0 ||
      t.indexOf("LIGHT") >= 0 || t.indexOf("LED") >= 0) {
    return false;
  }
  if (t.indexOf("SMALL") >= 0 || t == "SQUIRREL" || t == "DOG" || t == "CAT" ||
      t == "RABBIT" || t == "RACCOON" || t == "FOX" || t == "1") {
    return true;
  }
  if (t.indexOf("LARGE") >= 0 || t == "DEER" || t == "COYOTE" ||
      t == "COW" || t == "BEAR" || t == "2") {
    return true;
  }
  if (t == "WATER" || t == "PUMP" || t == "WATER_TEST" || t == "PUMP_TEST" ||
      t.startsWith("WATER_TEST_") || t.startsWith("PUMP_TEST_")) {
    return true;
  }
  return false;
}

uint32_t getRandomizedPumpDurationMs(const String& target) {
  String t = target;
  t.toUpperCase();
  t.trim();

  if (!isPumpTargetAllowed(t)) {
    return 0;
  }

  // Class 1 (SMALL MAMMAL: Water + Sound) -> Randomized 5.0s - 9.0s ON duration
  if (t.indexOf("SMALL") >= 0 || t == "SQUIRREL" || t == "DOG" || t == "CAT" ||
      t == "RABBIT" || t == "RACCOON" || t == "FOX" || t == "1") {
    return (uint32_t)random(5000, 9001);   // 5000ms - 9000ms (matches SMALL MAMMAL synchronized tier)
  }

  // Class 2 (LARGE MAMMAL: Higher Class Level, Water + Sound + Light) -> Randomized 8.0s - 14.0s ON duration
  if (t.indexOf("LARGE") >= 0 || t == "DEER" || t == "COYOTE" ||
      t == "COW" || t == "BEAR" || t == "2") {
    return (uint32_t)random(8000, 14001);  // 8000ms - 14000ms (matches LARGE MAMMAL synchronized tier)
  }

  // Manual Water Sprinkler Test (WATER_TEST / WATER / PUMP_TEST) -> Randomized 2.5s - 6.0s
  return (uint32_t)random(2500, 6001);
}

void setupPump() {
  randomSeed(esp_random());
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW); // Default to off

  if (pumpTaskHandle == NULL) {
    xTaskCreatePinnedToCore(
      pumpWorkerTask,
      "PumpWorker",
      3072,
      NULL,
      1,
      &pumpTaskHandle,
      1
    );
  }
  Serial.printf("[PUMP] Zero-latency water pump worker initialized on GPIO %d (Core 1, Default: LOW/OFF)\n", PUMP_PIN);
}

bool isPumpActive() {
  return pumpRunning;
}

uint32_t getCurrentPumpDurationMs() {
  return pumpRunning ? pumpDurationMs : 0;
}

uint32_t getRemainingPumpDurationMs() {
  if (!pumpRunning || pumpDurationMs == 0) return 0;
  uint32_t elapsed = millis() - pumpStartTimeMs;
  if (elapsed >= pumpDurationMs) return 0;
  return pumpDurationMs - elapsed;
}

void stopPump() {
  portENTER_CRITICAL(&pumpMux);
  stopPumpRequested = true;
  pendingPumpDurationMs = 0;
  pumpCommandGen++;
  pumpRunning = false;
  pumpDurationMs = 0;
  portEXIT_CRITICAL(&pumpMux);
  silencePump();
  Serial.println("[PUMP] Water pump immediately turned OFF (GPIO 18 -> LOW).");
}

// ==========================================
// PERSISTENT ZERO-LATENCY PUMP WORKER TASK
// ==========================================
static void pumpWorkerTask(void* parameter) {
  for (;;) {
    // Sleep until woken instantaneously by triggerPump()
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    uint32_t onDurationMs = 0;
    uint32_t myGen = 0;

    portENTER_CRITICAL(&pumpMux);
    myGen = pumpCommandGen;
    onDurationMs = pendingPumpDurationMs;
    pendingPumpDurationMs = 0;
    if (onDurationMs > 0) {
      stopPumpRequested = false;
      pumpStartTimeMs = millis();
      pumpDurationMs = onDurationMs;
      pumpRunning = true;
    } else {
      pumpRunning = false;
      pumpDurationMs = 0;
    }
    portEXIT_CRITICAL(&pumpMux);

    if (onDurationMs == 0) {
      silencePump();
      continue;
    }

    // Stagger inductive pump engagement by 25ms when waking alongside buzzer/LED
    // so inrush current doesn't stack at t=0, while still shutting off at pumpStartTimeMs + onDurationMs.
    if (!waitPumpInterruptible(25)) {
      digitalWrite(PUMP_PIN, LOW);
      portENTER_CRITICAL(&pumpMux);
      if (pumpCommandGen == myGen) {
        pumpRunning = false;
        pumpDurationMs = 0;
      }
      portEXIT_CRITICAL(&pumpMux);
      continue;
    }

    Serial.printf("[PUMP] >>> Turning Water Pump ON (GPIO %d -> HIGH) for %u ms <<<\n", PUMP_PIN, onDurationMs);
    pinMode(PUMP_PIN, OUTPUT);
    digitalWrite(PUMP_PIN, HIGH);

    // Keep pump ON until the synchronized class deadline expires unless preempted/stopped
    waitPumpInterruptible(onDurationMs);

    // Turn pump OFF (Default LOW)
    digitalWrite(PUMP_PIN, LOW);
    uint32_t elapsed = millis() - pumpStartTimeMs;
    portENTER_CRITICAL(&pumpMux);
    if (pumpCommandGen == myGen) {
      pumpRunning = false;
      pumpDurationMs = 0;
    }
    portEXIT_CRITICAL(&pumpMux);
    Serial.printf("[PUMP] Water Pump OFF (GPIO %d -> LOW, %lu ms elapsed)\n", PUMP_PIN, elapsed);
  }
}

uint32_t triggerPump(const String& target, uint32_t durationMs) {
  String t = target;
  t.toUpperCase();
  t.trim();

  // Safety Override (SAFE / HUMAN / STOP / OFF)
  if (t == "OFF" || t == "STOP" || t == "NONE" || t == "SAFE" || t == "HUMAN" || t == "3") {
    stopPump();
    return 0;
  }

  // Enforce strict allowlist BEFORE applying caller-provided durationMs
  if (!isPumpTargetAllowed(t)) {
    stopPump();
    return 0;
  }

  // Respect caller-provided durationMs when supplied (to synchronize shutoff across active deterrents),
  // otherwise roll a randomized tier duration on-device.
  uint32_t resolvedDuration = (durationMs > 0)
                                ? durationMs
                                : getRandomizedPumpDurationMs(t);

  if (resolvedDuration == 0) {
    stopPump();
    return 0;
  }

  portENTER_CRITICAL(&pumpMux);
  stopPumpRequested = true; // Preempt any active cycle
  pendingPumpDurationMs = resolvedDuration;
  pumpCommandGen++;
  portEXIT_CRITICAL(&pumpMux);

  if (pumpTaskHandle != NULL) {
    xTaskNotifyGive(pumpTaskHandle);
  }

  return resolvedDuration;
}
