#include "websocket.h"
#include "buzzer.h"
#include "pump.h"
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
      
      String welcome = "{\"event\":\"connected\",\"system\":\"Sentinel-ESP32\",\"last_target\":\"" + 
                        getLastTarget() + "\",\"buzzer_active\":" + (isBuzzerActive() ? "true" : "false") +
                        ",\"pump_active\":" + (isPumpActive() ? "true" : "false") +
                        ",\"duration_ms\":" + String(getCurrentDurationMs()) +
                        ",\"remaining_ms\":" + String(getRemainingDurationMs()) +
                        ",\"pump_duration_ms\":" + String(getCurrentPumpDurationMs()) + "}";
      webSocket.sendTXT(num, welcome);
      break;
    }

    case WStype_TEXT: {
      String msg = String((char*)payload);
      Serial.printf("[WS] Received from [%u]: %s\n", num, msg.c_str());

      String target = "";
      uint32_t requestedDurationMs = 0;

      if (msg.startsWith("{")) {
        target = extractJsonValue(msg, "animal");
        if (target.length() == 0) target = extractJsonValue(msg, "target");
        if (target.length() == 0) target = extractJsonValue(msg, "action");

        String durStr = extractJsonValue(msg, "duration");
        if (durStr.length() > 0) {
          uint32_t d = durStr.toInt();
          if (d > 0) requestedDurationMs = (d > 60) ? d : (d * 1000);
        }
      } else {
        target = msg;
      }

      target.trim();

      if (target.equalsIgnoreCase("STOP") || target.equalsIgnoreCase("OFF") || target.equalsIgnoreCase("SAFE")) {
        stopBuzzer();
        stopPump();
        broadcastWebSocket("{\"event\":\"stopped\",\"buzzer_active\":false,\"pump_active\":false,\"duration_ms\":0,\"remaining_ms\":0,\"pump_duration_ms\":0}");
      } else if (target.equalsIgnoreCase("WATER_TEST") || target.equalsIgnoreCase("PUMP_TEST") || target.equalsIgnoreCase("WATER")) {
        uint32_t pumpDur = triggerPump("WATER_TEST", requestedDurationMs);
        String ack = "{\"event\":\"actuator_test\",\"target\":\"WATER_TEST\",\"duration_ms\":" + String(pumpDur) +
                     ",\"pump_duration_ms\":" + String(pumpDur) +
                     ",\"buzzer_active\":" + (isBuzzerActive() ? "true" : "false") +
                     ",\"pump_active\":true}";
        broadcastWebSocket(ack);
      } else if (target.equalsIgnoreCase("LIGHT_TEST")) {
        uint32_t simDur = (requestedDurationMs > 0) ? requestedDurationMs : 4500;
        String ack = "{\"event\":\"actuator_test\",\"target\":\"LIGHT_TEST\",\"duration_ms\":" + String(simDur) +
                     ",\"buzzer_active\":" + (isBuzzerActive() ? "true" : "false") +
                     ",\"pump_active\":" + (isPumpActive() ? "true" : "false") + "}";
        broadcastWebSocket(ack);
      } else if (target.length() > 0) {
        uint32_t actualDurationMs = triggerDeterrent(target, requestedDurationMs);
        uint32_t pumpDurMs = triggerPump(target, 0);
        bool pumpOn = (pumpDurMs > 0) || isPumpActive();
        String ack = "{\"event\":\"triggered\",\"target\":\"" + target +
                     "\",\"duration_ms\":" + String(actualDurationMs) +
                     ",\"remaining_ms\":" + String(actualDurationMs) +
                     ",\"pump_duration_ms\":" + String(pumpDurMs) +
                     ",\"buzzer_active\":true,\"pump_active\":" + (pumpOn ? "true" : "false") + "}";
        broadcastWebSocket(ack);
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
