#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include "buzzer.h"
#include "pump.h"
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
    .btn-test { background: #8957e5; color: white; }
    .btn-stop { background: #30363d; color: #f85149; border: 1px solid #f85149; }
    .btn:hover { opacity: 0.85; }
    .status-box { font-family: monospace; font-size: 13px; background: #000; padding: 10px; border-radius: 4px; color: #3fb950; margin-top: 10px; word-break: break-all; }
  </style>
</head>
<body>
  <h1>Sentinel Actuator Node</h1>
  <div class="badge">SOFTAP ONLINE: 192.168.4.1 (GPIO 17 BUZZER + GPIO 18 PUMP)</div>

  <div class="card">
    <h3 style="margin-top:0;">Manual Trigger (Randomized by Class Level)</h3>
    <button class="btn btn-bird" onclick="sendCmd('BIRD')">BIRD: Sound 3-6s (Pump OFF)</button>
    <button class="btn btn-small" onclick="sendCmd('SMALL MAMMAL')">SMALL MAMMAL: Sound 5-9s + Pump 2.5-5s</button>
    <button class="btn btn-large" onclick="sendCmd('LARGE MAMMAL')">LARGE MAMMAL: Sound 8-14s + Pump 5-9s</button>
    <button class="btn btn-water" onclick="sendCmd('WATER_TEST')">Water Pump Test Only (GPIO 18: 2.5-5s)</button>
    <button class="btn btn-test" onclick="sendCmd('SOUND_TEST')">Sound Pattern Test Only (GPIO 17)</button>
    <button class="btn btn-stop" onclick="sendCmd('STOP')">Silence / Stop All (SAFE Override)</button>
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
          ' | Pump: ' + data.pump_active + ' (' + (data.pump_duration_ms || 0) + 'ms)';
      })
      .catch(err => {
        document.getElementById('log').innerText = 'Error: ' + err;
      });
    }
  </script>
</body>
</html>
)rawliteral";

  setCorsHeaders();
  server.send(200, "text/html", html);
}

// 2. Telemetry and Status endpoint
void handleStatus() {
  setCorsHeaders();
  
  uint32_t uptimeSec = millis() / 1000;
  uint8_t stationCount = WiFi.softAPgetStationNum();

  uint32_t buzDur = getCurrentDurationMs();
  uint32_t pmpDur = getCurrentPumpDurationMs();
  uint32_t maxDur = (buzDur >= pmpDur) ? buzDur : pmpDur;

  uint32_t buzRem = getRemainingDurationMs();
  uint32_t pmpRem = getRemainingPumpDurationMs();
  uint32_t maxRem = (buzRem >= pmpRem) ? buzRem : pmpRem;

  String json = "{";
  json += "\"status\":\"ARMED\",";
  json += "\"system\":\"Sentinel ESP32 Deterrent\",";
  json += "\"softap_ssid\":\"" + String(AP_SSID) + "\",";
  json += "\"ip\":\"" + WiFi.softAPIP().toString() + "\",";
  json += "\"connected_stations\":" + String(stationCount) + ",";
  json += "\"last_target\":\"" + getLastTarget() + "\",";
  json += "\"buzzer_active\":" + String(isBuzzerActive() ? "true" : "false") + ",";
  json += "\"pump_active\":" + String(isPumpActive() ? "true" : "false") + ",";
  json += "\"duration_ms\":" + String(maxDur) + ",";
  json += "\"remaining_ms\":" + String(maxRem) + ",";
  json += "\"pump_duration_ms\":" + String(pmpDur) + ",";
  json += "\"pump_remaining_ms\":" + String(pmpRem) + ",";
  json += "\"uptime_sec\":" + String(uptimeSec);
  json += "}";

  server.send(200, "application/json", json);
}

// 3. Command Endpoint (Accepts POST JSON from Jetson / Laptop Dashboard / cURL)
void handleCommand() {
  setCorsHeaders();

  String target = "";
  uint32_t requestedDurationMs = 0; // 0 = use native ESP32 hardware-randomized duration per class

  if (server.hasArg("plain")) {
    String body = server.arg("plain");
    target = parseJsonField(body, "animal");
    if (target.length() == 0) target = parseJsonField(body, "target");
    if (target.length() == 0) target = parseJsonField(body, "action");
    
    String durStr = parseJsonField(body, "duration");
    if (durStr.length() > 0) {
      uint32_t parsedVal = durStr.toInt();
      if (parsedVal > 0) {
        requestedDurationMs = (parsedVal > 60) ? parsedVal : (parsedVal * 1000);
      }
    }
  }

  // Fallback to URL query or standard form arguments (e.g. /command?animal=SMALL&duration=6500)
  if (target.length() == 0 && server.hasArg("animal")) target = server.arg("animal");
  if (target.length() == 0 && server.hasArg("target")) target = server.arg("target");
  if (target.length() == 0 && server.hasArg("action")) target = server.arg("action");
  if (server.hasArg("duration")) {
    uint32_t d = server.arg("duration").toInt();
    if (d > 0) {
      requestedDurationMs = (d > 60) ? d : (d * 1000);
    }
  }

  target.trim();

  if (target.length() == 0) {
    server.send(400, "application/json", "{\"status\":\"error\",\"message\":\"Missing animal or target parameter\"}");
    return;
  }

  // 1. Human Safety Override (SAFE) or Explicit Stop -> Immediately shut off Buzzer & Water Pump
  if (target.equalsIgnoreCase("OFF") || target.equalsIgnoreCase("STOP") || target.equalsIgnoreCase("SAFE")) {
    stopBuzzer();
    stopPump();
    broadcastWebSocket("{\"event\":\"stopped\",\"buzzer_active\":false,\"pump_active\":false,\"duration_ms\":0,\"remaining_ms\":0,\"pump_duration_ms\":0}");
    server.send(200, "application/json", "{\"status\":\"success\",\"action\":\"STOPPED\",\"buzzer_active\":false,\"pump_active\":false,\"duration_ms\":0,\"pump_duration_ms\":0}");
    return;
  }

  // 2. Water Pump Test Command (GPIO 18 ONLY, Buzzer remains OFF)
  if (target.equalsIgnoreCase("WATER_TEST") || target.equalsIgnoreCase("PUMP_TEST") || target.equalsIgnoreCase("WATER")) {
    uint32_t pumpDurMs = triggerPump("WATER_TEST", requestedDurationMs);
    Serial.printf("[HTTP] Water Pump Test (GPIO %d): %u ms from %s\n", PUMP_PIN, pumpDurMs, server.client().remoteIP().toString().c_str());
    String wsMsg = "{\"event\":\"actuator_test\",\"target\":\"WATER_TEST\",\"duration_ms\":" + String(pumpDurMs) +
                   ",\"pump_duration_ms\":" + String(pumpDurMs) +
                   ",\"buzzer_active\":" + String(isBuzzerActive() ? "true" : "false") +
                   ",\"pump_active\":true}";
    broadcastWebSocket(wsMsg);
    server.send(200, "application/json",
                "{\"status\":\"success\",\"target\":\"WATER_TEST\",\"duration_ms\":" + String(pumpDurMs) +
                ",\"pump_duration_ms\":" + String(pumpDurMs) +
                ",\"buzzer_active\":" + String(isBuzzerActive() ? "true" : "false") +
                ",\"pump_active\":true}");
    return;
  }

  // 3. Light Test Command (Buzzer & Pump remain untouched)
  if (target.equalsIgnoreCase("LIGHT_TEST")) {
    uint32_t simDuration = (requestedDurationMs > 0) ? requestedDurationMs : 4500;
    Serial.printf("[HTTP] Light Test Command (%u ms) from %s\n", simDuration, server.client().remoteIP().toString().c_str());
    broadcastWebSocket("{\"event\":\"actuator_test\",\"target\":\"LIGHT_TEST\",\"duration_ms\":" + String(simDuration) +
                       ",\"buzzer_active\":" + String(isBuzzerActive() ? "true" : "false") +
                       ",\"pump_active\":" + String(isPumpActive() ? "true" : "false") + "}");
    server.send(200, "application/json",
                "{\"status\":\"success\",\"target\":\"LIGHT_TEST\",\"duration_ms\":" + String(simDuration) +
                ",\"buzzer_active\":" + String(isBuzzerActive() ? "true" : "false") +
                ",\"pump_active\":" + String(isPumpActive() ? "true" : "false") + "}");
    return;
  }

  // 4. Class Deterrent Trigger (BIRD / SMALL MAMMAL / LARGE MAMMAL) or SOUND_TEST*
  uint32_t actualDurationMs = triggerDeterrent(target, requestedDurationMs);
  uint32_t pumpDurMs = triggerPump(target, 0); // Randomizes pump duration by class level (0ms for BIRD / SOUND_TEST)
  bool pumpOn = (pumpDurMs > 0) || isPumpActive();

  Serial.printf("[HTTP] Triggered '%s' (Sound GPIO %d: %u ms, Water Pump GPIO %d: %u ms) from %s\n",
                target.c_str(), PIN_BUZZER, actualDurationMs, PUMP_PIN, pumpDurMs, server.client().remoteIP().toString().c_str());

  String payload = "{\"status\":\"success\",\"event\":\"triggered\",\"target\":\"" + target +
                   "\",\"duration_ms\":" + String(actualDurationMs) +
                   ",\"remaining_ms\":" + String(actualDurationMs) +
                   ",\"pump_duration_ms\":" + String(pumpDurMs) +
                   ",\"buzzer_active\":true,\"pump_active\":" + String(pumpOn ? "true" : "false") + "}";

  broadcastWebSocket(payload);
  server.send(200, "application/json", payload);
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
  Serial.println("  SENTINEL WILDLIFE DETERRENT ESP32 NODE (v2.1)");
  Serial.println("==================================================");

  // 1. Initialize Sound Buzzer (GPIO 17) & Water Pump (GPIO 18, Default LOW/OFF)
  setupBuzzer();
  setupPump();

  // 2. Start Wi-Fi SoftAP with Modem Sleep Disabled for Zero Latency (<5ms RTT)
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
