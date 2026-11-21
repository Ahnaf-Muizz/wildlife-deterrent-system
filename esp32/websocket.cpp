#include "websocket.h"
#include "buzzer.h"
#include "pump.h"
#include "led.h"
#include <WebSocketsServer.h>

static WebSocketsServer webSocket = WebSocketsServer(81);

// Lightweight JSON token extractor supporting both quoted strings and raw numbers
static String extractJsonValue(const String& json, const String& key) {
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

  if (json[valStart] == '"') {
    int endQuote = json.indexOf('"', valStart + 1);
    if (endQuote == -1) return "";
    return json.substring(valStart + 1, endQuote);
  }

  int valEnd = valStart;
  while (valEnd < (int)json.length() && json[valEnd] != ',' && json[valEnd] != '}' && json[valEnd] != ' ' && json[valEnd] != '\n' && json[valEnd] != '\r') {
    valEnd++;
  }
  return json.substring(valStart, valEnd);
}

static void onWebSocketEvent(uint8_t num, WStype_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.printf("[WS] Client [%u] Disconnected\n", num);
      break;

    case WStype_CONNECTED: {
      IPAddress ip = webSocket.remoteIP(num);
      Serial.printf("[WS] Client [%u] Connected from %s\n", num, ip.toString().c_str());
      
      uint32_t buzDur = getCurrentDurationMs();
      uint32_t pmpDur = getCurrentPumpDurationMs();
      uint32_t ledDur = getCurrentLedDurationMs();
      uint32_t maxDur = max(buzDur, max(pmpDur, ledDur));
      uint32_t maxRem = max(getRemainingDurationMs(), max(getRemainingPumpDurationMs(), getRemainingLedDurationMs()));

      String welcome = "{\"event\":\"connected\",\"firmware\":\"v2.5-stable\",\"system\":\"Sentinel-ESP32\",\"last_target\":\"" +
                        jsonEscape(getLastTarget()) + "\",\"buzzer_active\":" + (isBuzzerActive() ? "true" : "false") +
                        ",\"pump_active\":" + (isPumpActive() ? "true" : "false") +
                        ",\"led_active\":" + (isLedActive() ? "true" : "false") +
                        ",\"duration_ms\":" + String(maxDur) +
                        ",\"remaining_ms\":" + String(maxRem) +
                        ",\"pump_duration_ms\":" + String(pmpDur) +
                        ",\"led_duration_ms\":" + String(ledDur) + "}";
      webSocket.sendTXT(num, welcome);
      break;
    }

    case WStype_TEXT: {
      String msg;
      msg.reserve(length + 1);
      if (payload != NULL && length > 0) {
        msg.concat((const char*)payload, (unsigned int)length);
      }
      Serial.printf("[WS] Received from [%u]: %s\n", num, msg.c_str());

      String target = "";
      uint32_t requestedDurationMs = 0;

      if (msg.startsWith("{")) {
        target = extractJsonValue(msg, "animal");
        if (target.length() == 0) target = extractJsonValue(msg, "target");
        if (target.length() == 0) target = extractJsonValue(msg, "action");

        String durStr = extractJsonValue(msg, "duration");
        uint32_t parsed = parseSafeDurationMs(durStr);
        if (parsed > 0) requestedDurationMs = parsed;
      } else {
        target = msg;
      }

      target.trim();
      if (target.length() > 0) {
        int code = 200;
        String ack = executeUnifiedCommand(target, requestedDurationMs, "WS", &code);
        if (code != 200) {
          webSocket.sendTXT(num, ack);
        }
      }
      break;
    }

    default:
      break;
  }
}

void setupWebSocket() {
  webSocket.begin();
  webSocket.onEvent(onWebSocketEvent);
  Serial.println("[WS] WebSocket Server started on port 81 (ws://<IP>:81)");
}

void loopWebSocket() {
  webSocket.loop();
}

void broadcastWebSocket(String message) {
  webSocket.broadcastTXT(message);
}
