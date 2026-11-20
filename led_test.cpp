
#include <Arduino.h>

// =====================================================
// ESP32-S3 — Standalone LED / IRLZ44PBF MOSFET Test
// GPIO 2 controls the MOSFET gate.
// No Wi-Fi, HTTPS, or buzzer initialization.
// =====================================================

static constexpr uint8_t LIGHT_PIN = 2;

// MOSFET control polarity:
// false = GPIO HIGH turns MOSFET ON (normal N-channel
//         low-side switching, as currently wired).
// true  = GPIO LOW turns MOSFET ON (inverted control).
static constexpr bool MOSFET_ACTIVE_LOW = false;

// Flash pattern: 2 Hz, 50% duty cycle.
static constexpr uint32_t FLASH_PERIOD_MS = 500;
static constexpr uint32_t FLASH_ON_MS = 250;

// Diagnostic pattern: 2 seconds ON, 2 seconds OFF.
static constexpr uint32_t TEST_PERIOD_MS = 4000;
static constexpr uint32_t TEST_ON_MS = 2000;

enum class LedMode : uint8_t {
    OFF,
    ON,
    FLASH,
    TEST
};

static LedMode ledMode = LedMode::FLASH;

static uint32_t patternStartMs = 0;
static bool ledOutputState = false;

// =====================================================
// MOSFET OUTPUT CONTROL
// =====================================================

void setLed(bool on) {
    ledOutputState = on;

    const bool gpioLevel =
        MOSFET_ACTIVE_LOW ? !on : on;

    digitalWrite(LIGHT_PIN, gpioLevel ? HIGH : LOW);
}

// =====================================================
// MODE CONTROL
// =====================================================

void setMode(LedMode newMode) {
    ledMode = newMode;

    if (ledMode == LedMode::OFF) {
        setLed(false);
    }
    else if (ledMode == LedMode::ON) {
        setLed(true);
    }
    else {
        patternStartMs = millis();
        setLed(true);
    }
}

// =====================================================
// SERIAL HELP
// =====================================================

void printHelp() {
    Serial.println();
    Serial.println(F("========== LED MOSFET TEST =========="));
    Serial.println(F("f = Flash at 2 Hz"));
    Serial.println(F("1 = LED continuously ON"));
    Serial.println(F("0 = LED OFF"));
    Serial.println(F("t = Diagnostic: 2 sec ON / 2 sec OFF"));
    Serial.println(F("h = Show help"));
    Serial.println(F("===================================="));
    Serial.println();
}

// =====================================================
// SERIAL COMMAND PROCESSING
// =====================================================

void handleSerial() {
    while (Serial.available() > 0) {
        const char command = Serial.read();

        switch (command) {

            case 'f':
            case 'F':
                setMode(LedMode::FLASH);
                Serial.println(F("Mode: 2 Hz FLASH"));
                break;

            case '1':
                setMode(LedMode::ON);
                Serial.println(F("Mode: CONTINUOUS ON"));
                break;

            case '0':
                setMode(LedMode::OFF);
                Serial.println(F("Mode: OFF"));
                break;

            case 't':
            case 'T':
                setMode(LedMode::TEST);
                Serial.println(F("Mode: 2-second diagnostic test"));
                break;

            case 'h':
            case 'H':
                printHelp();
                break;

            case '\r':
            case '\n':
                break;

            default:
                Serial.println(F("Unknown command. Send h for help."));
                break;
        }
    }
}

// =====================================================
// NON-BLOCKING LED PATTERN UPDATE
// =====================================================

void updateLed() {

    if (ledMode != LedMode::FLASH &&
        ledMode != LedMode::TEST) {
        return;
    }

    const uint32_t elapsed = millis() - patternStartMs;

    uint32_t period;
    uint32_t onTime;

    if (ledMode == LedMode::FLASH) {
        period = FLASH_PERIOD_MS;
        onTime = FLASH_ON_MS;
    }
    else {
        period = TEST_PERIOD_MS;
        onTime = TEST_ON_MS;
    }

    const bool shouldBeOn = (elapsed % period) < onTime;

    if (shouldBeOn != ledOutputState) {
        setLed(shouldBeOn);
    }
}

// =====================================================
// SETUP
// =====================================================

void setup() {

    // Initialize GPIO in the OFF state.
    pinMode(LIGHT_PIN, OUTPUT);
    setLed(false);

    Serial.begin(115200);

    delay(250);

    Serial.println();
    Serial.println(F("ESP32-S3 MOSFET LED TEST"));
    Serial.println(F("Control GPIO: 2"));
    Serial.println(F("MOSFET: IRLZ44PBF"));
    Serial.println(
        MOSFET_ACTIVE_LOW
        ? F("Control polarity: ACTIVE LOW")
        : F("Control polarity: ACTIVE HIGH")
    );

    printHelp();

    setMode(LedMode::FLASH);
}

// =====================================================
// MAIN LOOP
// =====================================================

void loop() {
    handleSerial();
    updateLed();
}
