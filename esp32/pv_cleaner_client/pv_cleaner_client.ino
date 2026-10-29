// pv_cleaner_client.ino
// ESP32 side of the Hilla PV-cleaning AI: every 14 min ask the server for the command,
// and when it says "clean" (with a command_id not run before) switch the brush + pump relays on.
//
// Board: ESP32 (Arduino core). Library: ArduinoJson v7 (Arduino IDE -> Library Manager).
// Put your Wi-Fi name/password in secrets.h (copy secrets.example.h). secrets.h is never published.
//
// Safety, all enforced here on the ESP32 itself:
//   - no answer / bad answer / no Wi-Fi  -> do nothing
//   - same command_id is never run twice (saved in flash, survives a reboot)
//   - a run never lasts longer than HARD_CAP_MS (30 min), whatever the server says
//   - all relays OFF at boot

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include "secrets.h"  // WIFI_SSID, WIFI_PASS

const char* COMMAND_URL = "https://hilla-pv-cleaner.onrender.com/command";  // your Render address

const int RELAY_BRUSH = 26;  // change to your wiring
const int RELAY_PUMP = 27;
const int RELAY_ON = LOW;    // most relay modules switch on LOW; use HIGH if yours is active-high

const unsigned long POLL_MS = 14UL * 60 * 1000;         // < 15 min keeps free Render awake
const unsigned long CLEAN_CYCLE_MS = 30UL * 60 * 1000;  // your normal cleaning cycle length
const unsigned long HARD_CAP_MS = 30UL * 60 * 1000;     // absolute maximum run time

Preferences prefs;
unsigned long lastPoll = 0, runStart = 0, runMs = 0;
bool running = false, polledOnce = false;

void relays(bool on) {
  digitalWrite(RELAY_BRUSH, on ? RELAY_ON : !RELAY_ON);
  digitalWrite(RELAY_PUMP, on ? RELAY_ON : !RELAY_ON);
}

bool wifiReady() {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.reconnect();
  for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) delay(1000);
  return WiFi.status() == WL_CONNECTED;
}

bool fetchCommand(JsonDocument& doc) {
  if (!wifiReady()) return false;
  WiFiClientSecure client;
  client.setInsecure();  // shortcut: HTTPS without certificate check; add the server's root CA to harden
  HTTPClient http;
  http.setConnectTimeout(30000);
  http.setTimeout(60000);  // free Render can take ~1 min to wake up
  if (!http.begin(client, COMMAND_URL)) return false;
  int code = http.GET();
  bool ok = code == 200 && deserializeJson(doc, http.getString()) == DeserializationError::Ok;
  http.end();
  return ok;
}

void poll() {
  JsonDocument doc;
  bool ok = fetchCommand(doc);
  if (!ok) {  // first request may only wake the server up: try once more
    delay(30000);
    ok = fetchCommand(doc);
  }
  if (!ok) {
    Serial.println("no command -> do nothing");
    return;
  }
  const char* action = doc["action"] | "wait";
  const char* id = doc["command_id"] | "";
  const char* reason = doc["reason"] | "";
  Serial.printf("action=%s id=%s reason=%s\n", action, id, reason);

  if (strcmp(action, "clean") != 0 || id[0] == '\0') return;
  if (prefs.getString("last_id", "") == id) return;  // this command was already executed
  prefs.putString("last_id", id);                      // save first, so a reboot mid-run never repeats it

  unsigned long serverMax = (unsigned long)(doc["max_duration_min"] | 30) * 60000UL;
  runMs = min(CLEAN_CYCLE_MS, min(serverMax, HARD_CAP_MS));
  runStart = millis();
  running = true;
  relays(true);
  Serial.printf("CLEAN start for %lu min\n", runMs / 60000UL);
}

void setup() {
  Serial.begin(115200);
  digitalWrite(RELAY_BRUSH, !RELAY_ON);  // set OFF level before enabling the pins
  digitalWrite(RELAY_PUMP, !RELAY_ON);
  pinMode(RELAY_BRUSH, OUTPUT);
  pinMode(RELAY_PUMP, OUTPUT);
  relays(false);
  prefs.begin("pvclean", false);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

void loop() {
  if (running && millis() - runStart >= runMs) {  // stop on time even if Wi-Fi is gone
    relays(false);
    running = false;
    Serial.println("CLEAN done");
  }
  if (!running && (!polledOnce || millis() - lastPoll >= POLL_MS)) {
    polledOnce = true;
    lastPoll = millis();
    poll();
  }
  delay(1000);
}
