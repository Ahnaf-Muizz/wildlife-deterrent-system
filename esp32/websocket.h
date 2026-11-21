#ifndef WEBSOCKET_H
#define WEBSOCKET_H

#include <Arduino.h>

void setupWebSocket();
void loopWebSocket();
void broadcastWebSocket(String message);

String jsonEscape(const String& in);
uint32_t parseSafeDurationMs(const String& durStr);
String executeUnifiedCommand(const String& rawTarget, uint32_t requestedDurationMs, const char* sourceTag, int* httpCodeOut = nullptr);

#endif // WEBSOCKET_H
