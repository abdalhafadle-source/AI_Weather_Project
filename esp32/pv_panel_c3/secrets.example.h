// Copy this file to secrets.h (same folder) and put your keys in it.
// secrets.h is in .gitignore, so your passwords are never published.
// The home Wi-Fi itself is NOT set here: it is chosen from a phone (network "Hilla-PV-Setup", see the .ino).
#pragma once
// password of the ESP32's own setup network "Hilla-PV-Setup" (8 characters or more)
#define PORTAL_PASS "choose-a-setup-password"
// the same key as ACK_KEY on the server (long and random); the ESP32 sends it to prove who it is
#define ACK_KEY "same-long-random-key-as-on-the-server"
