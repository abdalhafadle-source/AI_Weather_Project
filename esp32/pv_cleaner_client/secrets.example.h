// Copy this file to secrets.h (same folder) and put your Wi-Fi details and the ACK key in it.
// secrets.h is in .gitignore, so your password is never published.
#pragma once
#define WIFI_SSID "your-wifi-name"
#define WIFI_PASS "your-wifi-password"
// the same key as ACK_KEY on the server (long and random); the ESP32 sends it to prove who it is
#define ACK_KEY "same-long-random-key-as-on-the-server"
