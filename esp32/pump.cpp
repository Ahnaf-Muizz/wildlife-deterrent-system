#include "pump.h"
#include <esp_system.h>

// Persistent FreeRTOS Worker & Atomic State Control for Water Pump
static TaskHandle_t pumpTaskHandle = NULL;
static portMUX_TYPE pumpMux = portMUX_INITIALIZER_UNLOCKED;

static volatile bool stopPumpRequested = false;
static volatile bool pumpRunning = false;
static volatile uint32_t pumpStartTimeMs = 0;
static volatile uint32_t pumpDurationMs = 0;
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

uint32_t getRandomizedPumpDurationMs(const String& target) {
  String t = target;
  t.toUpperCase();
  t.trim();

  // Bird (Class 0: Sound + Light only) or Sound/Light-only tests -> Do not activate water pump
  if (t.indexOf("BIRD") >= 0 || t == "0" ||
      t.indexOf("SOUND_TEST") >= 0 || t.indexOf("LIGHT_TEST") >= 0) {
    return 0;
  }

  // Class 1 (SMALL MAMMAL: Water + Sound) -> Randomized 2.5s - 5.0s ON duration
  if (t.indexOf("SMALL") >= 0 || t == "SQUIRREL" || t == "DOG" || t == "CAT" ||
      t == "RABBIT" || t == "RACCOON" || t == "FOX" || t == "1") {
    return (uint32_t)random(2500, 5001);   // 2500ms - 5000ms (centered around 3000ms test)
  }

  // Class 2 (LARGE MAMMAL: Higher Class Level, Water + Sound + Light) -> Randomized 5.0s - 9.0s ON duration
  if (t.indexOf("LARGE") >= 0 || t == "DEER" || t == "COYOTE" ||
      t == "COW" || t == "BEAR" || t == "2") {
    return (uint32_t)random(5000, 9001);   // 5000ms - 9000ms (higher class level = longer activation)
  }

  // Manual Water Sprinkler Test (WATER_TEST / WATER / PUMP_TEST) -> Randomized 2.5s - 5.0s
  if (t.indexOf("WATER") >= 0 || t.indexOf("PUMP") >= 0) {
    return (uint32_t)random(2500, 5001);
  }

  return 0;
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
      2,
      &pumpTaskHandle,
      0
    );
  }
  Serial.printf("[PUMP] Zero-latency water pump worker initialized on GPIO %d (Default: LOW/OFF)\n", PUMP_PIN);
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
  stopPumpRequested = true;
  pumpRunning = false;
  pumpDurationMs = 0;
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

    portENTER_CRITICAL(&pumpMux);
    onDurationMs = pendingPumpDurationMs;
    stopPumpRequested = false;
    pumpStartTimeMs = millis();
    pumpDurationMs = onDurationMs;
    pumpRunning = (onDurationMs > 0);
    portEXIT_CRITICAL(&pumpMux);

    if (onDurationMs == 0) {
      silencePump();
      continue;
    }

    Serial.printf("[PUMP] >>> Turning Water Pump ON (GPIO %d -> HIGH) for %u ms <<<\n", PUMP_PIN, onDurationMs);
    digitalWrite(PUMP_PIN, HIGH);

    // Keep pump ON for the randomized class duration unless preempted/stopped
    waitPumpInterruptible(onDurationMs);

    // Turn pump OFF (Default LOW)
    digitalWrite(PUMP_PIN, LOW);
    uint32_t elapsed = millis() - pumpStartTimeMs;
    pumpRunning = false;
    pumpDurationMs = 0;
    Serial.printf("[PUMP] Water Pump OFF (GPIO %d -> LOW, %lu ms elapsed)\n", PUMP_PIN, elapsed);
  }
}

uint32_t triggerPump(const String& target, uint32_t durationMs) {
  String t = target;
  t.toUpperCase();
  t.trim();

  // Safety Override (SAFE / STOP / OFF) or classes that do not use water (BIRD / SOUND_TEST / LIGHT_TEST)
  if (t == "OFF" || t == "STOP" || t == "NONE" || t == "SAFE" || t == "3" ||
      t.indexOf("BIRD") >= 0 || t == "0" ||
      t.indexOf("SOUND_TEST") >= 0 || t.indexOf("LIGHT_TEST") >= 0) {
    stopPump();
    return 0;
  }

  // For manual WATER_TEST, respect custom durationMs if supplied; for animal classes, randomize by class level
  bool isManualWaterTest = (t == "WATER_TEST" || t == "PUMP_TEST" || t == "WATER");
  uint32_t resolvedDuration = (isManualWaterTest && durationMs > 0)
                                ? durationMs
                                : getRandomizedPumpDurationMs(t);

  if (resolvedDuration == 0) {
    stopPump();
    return 0;
  }

  portENTER_CRITICAL(&pumpMux);
  stopPumpRequested = true; // Preempt any active cycle
  pendingPumpDurationMs = resolvedDuration;
  portEXIT_CRITICAL(&pumpMux);

  if (pumpTaskHandle != NULL) {
    xTaskNotifyGive(pumpTaskHandle);
  }

  return resolvedDuration;
}
