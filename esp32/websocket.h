#ifndef WEBSOCKET_H
#define WEBSOCKET_H

#include <Arduino.h>

void setupWebSocket();
void loopWebSocket();
void broadcastWebSocket(String message);

#endif // WEBSOCKET_H
