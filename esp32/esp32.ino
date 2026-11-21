#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <esp_system.h>
#include "buzzer.h"
#include "pump.h"
#include "led.h"
#include "websocket.h"

// ==========================================
// SOFTAP WI-FI CONFIGURATION
// ==========================================
const char* AP_SSID = "Wildlife-Deterrent-System-AP";
const char* AP_PASS = "haustein26";

IPAddress local_IP(192, 168, 4, 1);
// Gateway 0.0.0.0 tells iOS/Android via DHCP Option 3 that this SoftAP is a
// local-only LAN (no internet gateway), preventing mobile phones from routing
// 192.168.4.x HTTP traffic over 5G/LTE cellular data.
IPAddress gateway(0, 0, 0, 0);
IPAddress subnet(255, 255, 255, 0);

WebServer server(80);
static String lastDashboardHostIp = "192.168.4.2";

static void updateDashboardHostFromRemoteIp(const IPAddress& remote) {
  if (remote[0] == 192 && remote[1] == 168 && remote[2] == 4 && remote[3] != 1 && remote[3] != 0) {
    lastDashboardHostIp = remote.toString();
  }
}

String jsonEscape(const String& in) {
  String out;
  out.reserve(in.length() + 8);
  for (size_t i = 0; i < in.length(); i++) {
    char c = in[i];
    if (c == '\\') out += "\\\\";
    else if (c == '"') out += "\\\"";
    else if (c == '\n') out += "\\n";
    else if (c == '\r') out += "\\r";
    else if (c == '\t') out += "\\t";
    else if ((uint8_t)c >= 0x20) out += c;
  }
  return out;
}

uint32_t parseSafeDurationMs(const String& durStr) {
  String s = durStr;
  s.trim();
  if (s.length() == 0) return 0;
  long parsed = s.toInt();
  if (parsed <= 0) return 0;
  long ms = (parsed <= 60) ? (parsed * 1000L) : parsed;
  if (ms < 500) ms = 500;
  if (ms > 30000) ms = 30000;
  return (uint32_t)ms;
}

static bool isKnownWildlifeTarget(const String& u) {
  return (u.indexOf("BIRD") >= 0 || u == "0" ||
          u.indexOf("SMALL") >= 0 || u == "SQUIRREL" || u == "DOG" || u == "CAT" ||
          u == "RABBIT" || u == "RACCOON" || u == "FOX" || u == "1" ||
          u.indexOf("LARGE") >= 0 || u == "DEER" || u == "COYOTE" ||
          u == "COW" || u == "BEAR" || u == "2");
}

// Helper function to extract either a quoted string or raw number from JSON
static String parseJsonField(const String& json, const String& key) {
  String searchKey = "\"" + key + "\"";
  int keyIndex = json.indexOf(searchKey);
  if (keyIndex == -1) return "";

  int colonIndex = json.indexOf(':', keyIndex + searchKey.length());
  if (colonIndex == -1) return "";

  int valStart = colonIndex + 1;
  while (valStart < (int)json.length() && (json[valStart] == ' ' || json[valStart] == '\t' || json[valStart] == '\n' || json[valStart] == '\r')) {
    valStart++;
  }
  if (valStart >= (int)json.length()) return "";

  // Case 1: Quoted string value
  if (json[valStart] == '"') {
    int endQuote = json.indexOf('"', valStart + 1);
    if (endQuote == -1) return "";
    return json.substring(valStart + 1, endQuote);
  }

  // Case 2: Unquoted numeric / boolean token
  int valEnd = valStart;
  while (valEnd < (int)json.length() && json[valEnd] != ',' && json[valEnd] != '}' && json[valEnd] != ' ' && json[valEnd] != '\n' && json[valEnd] != '\r') {
    valEnd++;
  }
  return json.substring(valStart, valEnd);
}

// ==========================================
// HTTP HANDLERS
// ==========================================

void setCorsHeaders() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
}

void handleOptions() {
  setCorsHeaders();
  server.send(204);
}

// 1. Root Web Dashboard for manual bench testing
void handleRoot() {
  String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sentinel | ESP32 Deterrent Node</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; text-align: center; }
    h1 { color: #58a6ff; font-size: 22px; margin-bottom: 5px; }
    .badge { display: inline-block; padding: 5px 12px; border-radius: 12px; font-size: 13px; font-weight: bold; background: rgba(46,160,67,0.2); color: #3fb950; border: 1px solid #3fb950; margin-bottom: 20px; }
    .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; max-width: 440px; margin: 0 auto 20px auto; padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.4); text-align: left; }
    .btn { display: block; width: 100%; padding: 12px; margin: 10px 0; border: none; border-radius: 6px; font-size: 15px; font-weight: bold; cursor: pointer; transition: 0.2s; }
    .btn-bird { background: #1f6feb; color: white; }
    .btn-small { background: #d29922; color: black; }
    .btn-large { background: #f85149; color: white; }
    .btn-water { background: #00b4d8; color: black; }
    .btn-led { background: #f59e0b; color: black; }
    .btn-test { background: #8957e5; color: white; }
    .btn-stop { background: #30363d; color: #f85149; border: 1px solid #f85149; }
    .btn:hover { opacity: 0.85; }
    .status-box { font-family: monospace; font-size: 13px; background: #000; padding: 10px; border-radius: 4px; color: #3fb950; margin-top: 10px; word-break: break-all; }
  </style>
</head>
<body>
  <h1>Sentinel Actuator Node</h1>
  <div class="badge">SOFTAP ONLINE: 192.168.4.1 (v2.5-stable • GPIO 16 LED + GPIO 17 BUZZER + GPIO 18 PUMP)</div>

  <div class="card">
    <h3 style="margin-top:0;">Manual Trigger (Randomized by Class Level)</h3>
    <button class="btn btn-bird" onclick="sendCmd('BIRD')">BIRD: Sound + LED Flash (3-6s Synced Random)</button>
    <button class="btn btn-small" onclick="sendCmd('SMALL MAMMAL')">SMALL MAMMAL: Sound + Pump (5-9s Synced Random)</button>
    <button class="btn btn-large" onclick="sendCmd('LARGE MAMMAL')">LARGE MAMMAL: Sound + LED + Pump (8-14s Synced Random)</button>
    <button class="btn btn-water" onclick="sendCmd('WATER_TEST')">Water Pump Test Only (GPIO 18: 2.5-6s)</button>
    <button class="btn btn-led" onclick="sendCmd('LIGHT_TEST')">LED Flash Test Only (GPIO 16: 3.5-7.5s)</button>
    <button class="btn btn-test" onclick="sendCmd('SOUND_TEST')">Sound Pattern Test Only (GPIO 17)</button>
    <button class="btn btn-stop" onclick="sendCmd('STOP')">Silence / Stop All (SAFE Override)</button>
    <a class="btn btn-water" style="text-decoration:none;text-align:center;" href="http://__DASHBOARD_HOST__:5002/qr-upload">Open Mobile AI Upload Portal</a>
    <div class="status-box" id="log">Waiting for action...</div>
  </div>

  <script>
    function sendCmd(target) {
      document.getElementById('log').innerText = 'Sending: ' + target + '...';
      fetch('/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ animal: target })
      })
      .then(res => res.json())
      .then(data => {
        document.getElementById('log').innerText =
          'Target: ' + (data.target || data.action) +
          ' | Duration: ' + (data.duration_ms || 0) + 'ms' +
          ' | Buzzer: ' + data.buzzer_active +
          ' | Pump: ' + data.pump_active + ' (' + (data.pump_duration_ms || 0) + 'ms)' +
          ' | LED: ' + data.led_active + ' (' + (data.led_duration_ms || 0) + 'ms)';
      })
      .catch(err => {
        document.getElementById('log').innerText = 'Error: ' + err;
      });
    }
  </script>
</body>
</html>
)rawliteral";

  html.replace("__DASHBOARD_HOST__", lastDashboardHostIp);
  setCorsHeaders();
  server.send(200, "text/html", html);
}

static const char* getResetReasonStr() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:  return "POWERON";
    case ESP_RST_SW:       return "SW";
    case ESP_RST_PANIC:    return "PANIC";
    case ESP_RST_INT_WDT:  return "INT_WDT";
    case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT:      return "WDT";
    case ESP_RST_BROWNOUT: return "BROWNOUT";
    case ESP_RST_USB:      return "USB";
    default:               return "OTHER";
  }
}

// 2. Telemetry and Status endpoint
void handleStatus() {
  setCorsHeaders();
  updateDashboardHostFromRemoteIp(server.client().remoteIP());

  uint32_t uptimeSec = millis() / 1000;
  uint8_t stationCount = WiFi.softAPgetStationNum();

  uint32_t buzDur = getCurrentDurationMs();
  uint32_t pmpDur = getCurrentPumpDurationMs();
  uint32_t ledDur = getCurrentLedDurationMs();
  uint32_t maxDur = max(buzDur, max(pmpDur, ledDur));

  uint32_t buzRem = getRemainingDurationMs();
  uint32_t pmpRem = getRemainingPumpDurationMs();
  uint32_t ledRem = getRemainingLedDurationMs();
  uint32_t maxRem = max(buzRem, max(pmpRem, ledRem));

  String json = "{";
  json += "\"firmware\":\"v2.5-stable\",";
  json += "\"status\":\"ARMED\",";
  json += "\"system\":\"Sentinel ESP32 Deterrent\",";
  json += "\"softap_ssid\":\"" + jsonEscape(String(AP_SSID)) + "\",";
  json += "\"ip\":\"" + WiFi.softAPIP().toString() + "\",";
  json += "\"connected_stations\":" + String(stationCount) + ",";
  json += "\"reset_reason\":\"" + String(getResetReasonStr()) + "\",";
  json += "\"free_heap\":" + String(ESP.getFreeHeap()) + ",";
  json += "\"last_target\":\"" + jsonEscape(getLastTarget()) + "\",";
  json += "\"buzzer_active\":" + String(isBuzzerActive() ? "true" : "false") + ",";
  json += "\"pump_active\":" + String(isPumpActive() ? "true" : "false") + ",";
  json += "\"led_active\":" + String(isLedActive() ? "true" : "false") + ",";
  json += "\"duration_ms\":" + String(maxDur) + ",";
  json += "\"remaining_ms\":" + String(maxRem) + ",";
  json += "\"buzzer_duration_ms\":" + String(buzDur) + ",";
  json += "\"buzzer_remaining_ms\":" + String(buzRem) + ",";
  json += "\"pump_duration_ms\":" + String(pmpDur) + ",";
  json += "\"pump_remaining_ms\":" + String(pmpRem) + ",";
  json += "\"led_duration_ms\":" + String(ledDur) + ",";
  json += "\"led_remaining_ms\":" + String(ledRem) + ",";
  json += "\"uptime_sec\":" + String(uptimeSec);
  json += "}";

  server.send(200, "application/json", json);
}

// Shared unified command handler for both HTTP and WebSocket
String executeUnifiedCommand(const String& rawTarget, uint32_t requestedDurationMs, const char* sourceTag, int* httpCodeOut) {
  String target = rawTarget;
  target.trim();
  String u = target;
  u.toUpperCase();
  String escTarget = jsonEscape(target);

  if (httpCodeOut) *httpCodeOut = 200;

  // 1. Human Safety Override (SAFE / HUMAN) or Explicit Stop -> Immediately shut off Buzzer, Water Pump & LED
  if (u == "OFF" || u == "STOP" || u == "SAFE" || u == "HUMAN" || u == "NONE" || u == "3") {
    stopBuzzer();
    stopPump();
    stopLed();
    Serial.printf("[%s] Safety STOP / SAFE override executed (%s)\n", sourceTag, target.c_str());
    String wsMsg = "{\"status\":\"success\",\"event\":\"stopped\",\"firmware\":\"v2.5-stable\",\"action\":\"STOPPED\",\"buzzer_active\":false,\"pump_active\":false,\"led_active\":false,\"duration_ms\":0,\"remaining_ms\":0,\"pump_duration_ms\":0,\"led_duration_ms\":0}";
    broadcastWebSocket(wsMsg);
    return wsMsg;
  }

  // 2. Water Pump Test Command (GPIO 18 ONLY, Buzzer & LED remain untouched)
  if (u == "WATER_TEST" || u == "PUMP_TEST" || u == "WATER" ||
      u.startsWith("WATER_TEST_") || u.startsWith("PUMP_TEST_")) {
    uint32_t pumpDurMs = triggerPump("WATER_TEST", requestedDurationMs);
    Serial.printf("[%s] Water Pump Test (GPIO %d): %u ms\n", sourceTag, PUMP_PIN, pumpDurMs);
    String wsMsg = "{\"status\":\"success\",\"event\":\"actuator_test\",\"firmware\":\"v2.5-stable\",\"target\":\"" + escTarget +
                   "\",\"duration_ms\":" + String(pumpDurMs) +
                   ",\"pump_duration_ms\":" + String(pumpDurMs) +
                   ",\"buzzer_active\":" + String(isBuzzerActive() ? "true" : "false") +
                   ",\"pump_active\":" + String(pumpDurMs > 0 ? "true" : "false") +
                   ",\"led_active\":" + String(isLedActive() ? "true" : "false") + "}";
    broadcastWebSocket(wsMsg);
    return wsMsg;
  }

  // 3. LED Strobe Test Command (GPIO 16 ONLY, Buzzer & Pump remain untouched)
  if (u == "LIGHT_TEST" || u == "LED_TEST" || u == "LIGHT" || u == "LED" ||
      u.startsWith("LIGHT_TEST_") || u.startsWith("LED_TEST_")) {
    uint32_t ledDurMs = triggerLed(u, requestedDurationMs);
    Serial.printf("[%s] LED Flash Test (GPIO %d): %u ms\n", sourceTag, LED_PIN, ledDurMs);
    String wsMsg = "{\"status\":\"success\",\"event\":\"actuator_test\",\"firmware\":\"v2.5-stable\",\"target\":\"" + escTarget +
                   "\",\"duration_ms\":" + String(ledDurMs) +
                   ",\"led_duration_ms\":" + String(ledDurMs) +
                   ",\"buzzer_active\":" + String(isBuzzerActive() ? "true" : "false") +
                   ",\"pump_active\":" + String(isPumpActive() ? "true" : "false") +
                   ",\"led_active\":" + String(ledDurMs > 0 ? "true" : "false") + "}";
    broadcastWebSocket(wsMsg);
    return wsMsg;
  }

  // 4. Sound Buzzer Test Command (GPIO 17 ONLY, Water Pump & LED remain untouched)
  if (u == "SOUND_TEST" || u == "BUZZER_TEST" || u == "SOUND" || u == "BUZZER" ||
      u.startsWith("SOUND_TEST_") || u.startsWith("BUZZER_TEST_")) {
    uint32_t buzDurMs = triggerDeterrent(u, requestedDurationMs);
    Serial.printf("[%s] Sound Pattern Test (GPIO %d): %u ms (Pump/LED untouched)\n", sourceTag, PIN_BUZZER, buzDurMs);
    String wsMsg = "{\"status\":\"success\",\"event\":\"actuator_test\",\"firmware\":\"v2.5-stable\",\"target\":\"" + escTarget +
                   "\",\"duration_ms\":" + String(buzDurMs) +
                   ",\"buzzer_duration_ms\":" + String(buzDurMs) +
                   ",\"pump_duration_ms\":" + String(getCurrentPumpDurationMs()) +
                   ",\"led_duration_ms\":" + String(getCurrentLedDurationMs()) +
                   ",\"buzzer_active\":" + String(buzDurMs > 0 ? "true" : "false") +
                   ",\"pump_active\":" + String(isPumpActive() ? "true" : "false") +
                   ",\"led_active\":" + String(isLedActive() ? "true" : "false") + "}";
    broadcastWebSocket(wsMsg);
    return wsMsg;
  }

  // 5. Strict Allowlist for Synchronized Class Deterrent Trigger (BIRD / SMALL MAMMAL / LARGE MAMMAL)
  if (!isKnownWildlifeTarget(u)) {
    if (httpCodeOut) *httpCodeOut = 400;
    Serial.printf("[%s] Rejected unknown target '%s'\n", sourceTag, target.c_str());
    return "{\"status\":\"error\",\"firmware\":\"v2.5-stable\",\"message\":\"Unknown deterrent target\"}";
  }

  uint32_t actualDurationMs = triggerDeterrent(u, requestedDurationMs);
  uint32_t pumpDurMs = triggerPump(u, actualDurationMs); // Synchronized turn-off with Buzzer (0ms for BIRD)
  uint32_t ledDurMs = triggerLed(u, actualDurationMs);   // Synchronized turn-off with Buzzer (0ms for SMALL MAMMAL)
  bool buzOn = (actualDurationMs > 0) || isBuzzerActive();
  bool pumpOn = (pumpDurMs > 0) || isPumpActive();
  bool ledOn = (ledDurMs > 0) || isLedActive();
  uint32_t overallDurMs = max(actualDurationMs, max(pumpDurMs, ledDurMs));

  Serial.printf("[%s] Triggered '%s' (Sound GPIO %d: %u ms, LED GPIO %d: %u ms, Water Pump GPIO %d: %u ms)\n",
                sourceTag, target.c_str(), PIN_BUZZER, actualDurationMs, LED_PIN, ledDurMs, PUMP_PIN, pumpDurMs);

  String payload = "{\"status\":\"success\",\"event\":\"triggered\",\"firmware\":\"v2.5-stable\",\"target\":\"" + escTarget +
                   "\",\"duration_ms\":" + String(overallDurMs) +
                   ",\"remaining_ms\":" + String(overallDurMs) +
                   ",\"pump_duration_ms\":" + String(pumpDurMs) +
                   ",\"led_duration_ms\":" + String(ledDurMs) +
                   ",\"buzzer_active\":" + String(buzOn ? "true" : "false") +
                   ",\"pump_active\":" + String(pumpOn ? "true" : "false") +
                   ",\"led_active\":" + String(ledOn ? "true" : "false") + "}";

  broadcastWebSocket(payload);
  return payload;
}

// 3. Command Endpoint (Accepts POST JSON from Jetson / Laptop Dashboard / cURL)
void handleCommand() {
  setCorsHeaders();
  updateDashboardHostFromRemoteIp(server.client().remoteIP());

  String target = "";
  uint32_t requestedDurationMs = 0; // 0 = use native ESP32 hardware-randomized duration per class

  if (server.hasArg("plain")) {
    String body = server.arg("plain");
    target = parseJsonField(body, "animal");
    if (target.length() == 0) target = parseJsonField(body, "target");
    if (target.length() == 0) target = parseJsonField(body, "action");

    String durStr = parseJsonField(body, "duration");
    uint32_t parsed = parseSafeDurationMs(durStr);
    if (parsed > 0) requestedDurationMs = parsed;
  }

  // Fallback to URL query or standard form arguments (e.g. /command?animal=SMALL&duration=6500)
  if (target.length() == 0 && server.hasArg("animal")) target = server.arg("animal");
  if (target.length() == 0 && server.hasArg("target")) target = server.arg("target");
  if (target.length() == 0 && server.hasArg("action")) target = server.arg("action");
  if (server.hasArg("duration")) {
    uint32_t parsed = parseSafeDurationMs(server.arg("duration"));
    if (parsed > 0) requestedDurationMs = parsed;
  }

  target.trim();

  if (target.length() == 0) {
    server.send(400, "application/json", "{\"status\":\"error\",\"firmware\":\"v2.5-stable\",\"message\":\"Missing animal or target parameter\"}");
    return;
  }

  int httpCode = 200;
  String respJson = executeUnifiedCommand(target, requestedDurationMs, "HTTP", &httpCode);
  server.send(httpCode, "application/json", respJson);
}

void handleNotFound() {
  setCorsHeaders();
  server.send(404, "application/json", "{\"status\":\"error\",\"message\":\"Endpoint not found\"}");
}

// ==========================================
// SETUP & LOOP
// ==========================================

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n==================================================");
  Serial.println("  SENTINEL WILDLIFE DETERRENT ESP32 NODE (v2.5-stable)");
  Serial.println("==================================================");
  Serial.printf("[SYS] Reset reason: %s | Free heap: %u\n", getResetReasonStr(), ESP.getFreeHeap());

  // 1. Initialize Sound Buzzer (GPIO 17), LED MOSFET (GPIO 16), & Water Pump (GPIO 18) — Default OFF
  setupBuzzer();
  setupLed();
  setupPump();

  // 2. Start Wi-Fi SoftAP with Modem Sleep Disabled for Zero Latency (<5ms RTT)
  WiFi.persistent(false);
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(local_IP, gateway, subnet);
  bool apSuccess = WiFi.softAP(AP_SSID, AP_PASS);
  WiFi.setSleep(false);

  if (apSuccess) {
    Serial.printf("[WIFI] SoftAP '%s' Started Successfully (Low-Latency Mode)!\n", AP_SSID);
    Serial.printf("[WIFI] Access Point IP: %s\n", WiFi.softAPIP().toString().c_str());
    Serial.println("[WIFI] Connect Jetson Orin Nano / Laptop to this AP.");
  } else {
    Serial.println("[WIFI] ERROR: Failed to start SoftAP.");
  }

  // 3. Initialize mDNS (http://esp32.local)
  if (MDNS.begin("esp32")) {
    Serial.println("[MDNS] Responder started: http://esp32.local");
  }

  // 4. Initialize WebSocket Server (Port 81)
  setupWebSocket();

  // 5. Register HTTP Endpoints (Port 80)
  server.on("/", HTTP_GET, handleRoot);
  server.on("/upload", HTTP_GET, []() {
    setCorsHeaders();
    server.sendHeader("Location", "http://" + lastDashboardHostIp + ":5002/qr-upload", true);
    server.send(302, "text/plain", "Redirecting to Sentinel Upload Portal...");
  });
  server.on("/status", HTTP_GET, handleStatus);
  server.on("/command", HTTP_POST, handleCommand);
  server.on("/command", HTTP_GET, handleCommand);
  server.on("/command", HTTP_OPTIONS, handleOptions);
  server.onNotFound(handleNotFound);

  server.begin();
  Serial.println("[HTTP] REST API Server running on port 80");
  Serial.println("==================================================\n");
}

void loop() {
  server.handleClient();
  loopWebSocket();
}
