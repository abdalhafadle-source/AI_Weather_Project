// pv_panel_c3.ino
// The panel controller (ESP32-C3 SuperMini, next to the pump): the brain of the washing since 2026-11-22.
// Every 14 min it reads the command that our VPS writes every hour; on "clean" (a command_id not run before)
// it runs the pump and the brush relays, then tells the server (POST /ack). The handheld screen only shows
// data and can ask for a 1-minute manual wash over ESP-NOW (espnow_link.h); this board decides and runs it.
//
// Board: ESP32C3 Dev Module, "USB CDC On Boot: Enabled" (FQBN esp32:esp32:esp32c3:CDCOnBoot=cdc).
// Wiring (relay module, 2 channels): PUMP -> GPIO 4, BRUSH -> GPIO 5, VCC 5V, GND. Most modules switch on LOW.
// Wi-Fi is set from a phone (WiFiManager): network "Hilla-PV-Panel" (password PORTAL_PASS) opens for 3 min when
// the saved network is not reachable; hold the BOOT button (GPIO 9) 3 s to open it on purpose.
// secrets.h (copy secrets.example.h) holds ACK_KEY and PORTAL_PASS and is never published.
//
// One wash: pump on -> after PREWET_MS the brush starts -> RINSE_MS before the end the brush stops -> pump off.
// Safety, all enforced here: no answer / no Wi-Fi / clock not synced / command expired -> nothing; the same
// command_id never runs twice (saved in flash); a run never lasts longer than HARD_CAP_MS; at most 2 runs per
// day and 6 h between runs (auto and manual together); relays OFF at boot and when a run ends.

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include "ArduinoJson-v7.4.3.h"
#include <time.h>
#include "WiFiManager.h"
#include "secrets.h"  // ACK_KEY, PORTAL_PASS
#ifndef ACK_KEY
#error "Add ACK_KEY to secrets.h (see secrets.example.h): the same key as on the server"
#endif
#ifndef PORTAL_PASS
#error "Add PORTAL_PASS to secrets.h (see secrets.example.h): password of the Wi-Fi setup network, 8+ characters"
#endif
#include "root_ca.h"
#include "espnow_link.h"

const char* COMMAND_URL = "https://hilla-ai.duckdns.org/command";
const char* ACK_URL = "https://hilla-ai.duckdns.org/ack";
const char* PORTAL_NAME = "Hilla-PV-Panel";
const int PORTAL_S = 180;
const int SETUP_BUTTON = 9;           // BOOT button of the C3 SuperMini
const int WIFI_FAILS_TO_PORTAL = 3;

const int RELAY_PUMP = 4;             // change to your wiring
const int RELAY_BRUSH = 5;
const int RELAY_ON = LOW;             // most relay modules switch on LOW; use HIGH if yours is active-high

const unsigned long POLL_MS = 14UL * 60 * 1000;
const unsigned long CLEAN_CYCLE_MS = 30UL * 60 * 1000;
const unsigned long HARD_CAP_MS = 30UL * 60 * 1000;
const unsigned long MANUAL_MS = 60UL * 1000;
const unsigned long PREWET_MS = 15UL * 1000;   // pump alone first: never brush a dry panel
const unsigned long RINSE_MS = 15UL * 1000;    // pump alone at the end: rinse the dust away
const unsigned long STATUS_MS = 3000;          // status to the handheld screen
const long MIN_GAP_S = 6L * 3600;
const int MAX_PER_DAY = 2;

Preferences prefs;
unsigned long lastPoll = 0, runStart = 0, runMs = 0, lastStatus = 0;
bool running = false, polledOnce = false;
int wifiFails = 0;

// ESP-NOW: the callback runs in the radio task, so it only stores the request; loop() handles it
volatile bool washReq = false;
uint32_t rxSeq = 0, rxTs = 0;
void onLink(const uint8_t* mac, const uint8_t* data, int len) {
  LinkMsg m;
  if (linkCheck(data, len, m, rxSeq, rxTs) && m.type == LINK_WASH_REQ) washReq = true;
}

void pump(bool on) { digitalWrite(RELAY_PUMP, on ? RELAY_ON : !RELAY_ON); }
void brush(bool on) { digitalWrite(RELAY_BRUSH, on ? RELAY_ON : !RELAY_ON); }

void wifiSetup(bool force) {
  WiFiManager wm;
  wm.setConfigPortalTimeout(PORTAL_S);
  wm.setConnectTimeout(20);
  Serial.printf("Wi-Fi setup: if no network, join \"%s\" from a phone\n", PORTAL_NAME);
  bool ok = force ? wm.startConfigPortal(PORTAL_NAME, PORTAL_PASS) : wm.autoConnect(PORTAL_NAME, PORTAL_PASS);
  Serial.println(ok ? "Wi-Fi connected" : "Wi-Fi setup timed out -> will try again later");
  if (ok) Serial.println(linkBegin(onLink) ? "ESP-NOW ready" : "ESP-NOW failed");
}

long long isoToEpoch(const char* s) {
  int Y, M, D, h, m, sec, oh = 0, om = 0;
  char sign = 'Z';
  if (sscanf(s, "%d-%d-%dT%d:%d:%d%c%d:%d", &Y, &M, &D, &h, &m, &sec, &sign, &oh, &om) < 6) return -1;
  Y -= M <= 2;
  long era = Y / 400, yoe = Y - era * 400;
  long doy = (153 * (M + (M > 2 ? -3 : 9)) + 2) / 5 + D - 1;
  long days = era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719468;
  long off = (oh * 3600L + om * 60L) * (sign == '-' ? -1 : 1);
  return days * 86400LL + h * 3600L + m * 60L + sec - off;
}

bool wifiReady() {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.reconnect();
  for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) delay(1000);
  if (WiFi.status() == WL_CONNECTED) linkBegin(onLink);
  return WiFi.status() == WL_CONNECTED;
}

bool fetchCommand(JsonDocument& doc) {
  if (!wifiReady()) return false;
  for (int i = 0; i < 30 && time(nullptr) < 1700000000; i++) delay(500);
  WiFiClientSecure tls;
  tls.setCACert(ROOT_CAS);
  HTTPClient http;
  http.setConnectTimeout(30000);
  http.setTimeout(30000);
  if (!http.begin(tls, COMMAND_URL)) return false;
  http.addHeader("X-Key", ACK_KEY);
  http.addHeader("X-Last-Id", prefs.getString("last_id", ""));
  int code = http.GET();
  bool ok = code == 200 && deserializeJson(doc, http.getString()) == DeserializationError::Ok;
  http.end();
  return ok;
}

void sendAck(const char* id) {
  WiFiClientSecure tls;
  tls.setCACert(ROOT_CAS);
  HTTPClient http;
  http.setConnectTimeout(10000);
  http.setTimeout(10000);
  if (!http.begin(tls, ACK_URL)) return;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Key", ACK_KEY);
  int code = http.POST(String("{\"command_id\":\"") + id + "\"}");
  Serial.printf("ack -> %d\n", code);
  http.end();
}

int countToday() {
  time_t now = time(nullptr);
  long today = (long)((now + 3 * 3600) / 86400);  // Baghdad calendar day
  return prefs.getLong("day", -1) == today ? prefs.getInt("count", 0) : 0;
}

// local limits shared by auto and manual washes; returns the reason when not allowed, or nullptr
const char* blocked() {
  time_t now = time(nullptr);
  if (running) return "Already washing";
  if (now < 1700000000) return "Clock not set yet";
  if ((long long)now - prefs.getLong64("last_run", 0) < MIN_GAP_S || countToday() >= MAX_PER_DAY)
    return "Limit reached (6 h gap / 2 per day)";
  return nullptr;
}

void startRun(unsigned long ms) {
  time_t now = time(nullptr);
  int c = countToday();
  prefs.putLong64("last_run", (int64_t)now);  // save first, so a reboot mid-run never repeats it
  prefs.putLong("day", (long)((now + 3 * 3600) / 86400));
  prefs.putInt("count", c + 1);
  runMs = min(ms, HARD_CAP_MS);
  runStart = millis();
  running = true;
  pump(true);  // the brush follows after PREWET_MS (loop)
  Serial.printf("WASH start for %lu s\n", runMs / 1000UL);
}

void poll() {
  JsonDocument doc;
  bool ok = fetchCommand(doc);
  if (!ok) {
    delay(30000);
    ok = fetchCommand(doc);
  }
  if (!ok) { Serial.println("no command -> do nothing"); return; }
  const char* action = doc["action"] | "wait";
  const char* id = doc["command_id"] | "";
  Serial.printf("action=%s id=%s reason=%s\n", action, id, doc["reason"] | "");
  if (strcmp(action, "clean") != 0 || id[0] == '\0') return;
  long long until = isoToEpoch(doc["valid_until"] | "");
  time_t now = time(nullptr);
  if (now < 1700000000 || until < 0 || (long long)now > until) { Serial.println("expired / clock not set -> nothing"); return; }
  if (prefs.getString("last_id", "") == id) return;
  const char* why = blocked();
  if (why) { Serial.printf("local limit: %s\n", why); return; }
  prefs.putString("last_id", id);
  unsigned long serverMax = (unsigned long)(doc["max_duration_min"] | 30) * 60000UL;
  startRun(min(CLEAN_CYCLE_MS, serverMax));
  sendAck(id);
}

void sendStatus() {
  LinkMsg m = {};
  m.type = LINK_STATUS;
  m.running = running;
  m.countToday = time(nullptr) > 1700000000 ? countToday() : 0;
  unsigned long e = millis() - runStart;
  m.leftMs = running && e < runMs ? runMs - e : 0;
  m.runMs = running ? runMs : 0;
  m.lastRun = prefs.getLong64("last_run", 0);
  linkSend(m);
}

void setup() {
  Serial.begin(115200);
  digitalWrite(RELAY_PUMP, !RELAY_ON);  // OFF level before enabling the pins
  digitalWrite(RELAY_BRUSH, !RELAY_ON);
  pinMode(RELAY_PUMP, OUTPUT);
  pinMode(RELAY_BRUSH, OUTPUT);
  prefs.begin("pvpanel", false);
  pinMode(SETUP_BUTTON, INPUT_PULLUP);
  WiFi.mode(WIFI_STA);
  wifiSetup(false);
  configTime(0, 0, "pool.ntp.org", "time.google.com");
}

void loop() {
  if (running) {  // the wash sequence runs on time even if Wi-Fi is gone
    unsigned long e = millis() - runStart;
    bool brushOn = runMs > PREWET_MS + RINSE_MS && e >= PREWET_MS && e < runMs - RINSE_MS;
    brush(brushOn);
    if (e >= runMs) {
      brush(false);
      pump(false);
      running = false;
      Serial.println("WASH done");
    }
  }
  if (washReq) {  // manual wash asked from the handheld screen
    washReq = false;
    LinkMsg r = {};
    r.type = LINK_WASH_RESULT;
    const char* why = blocked();
    if (why) snprintf(r.text, sizeof r.text, "%s", why);
    else { startRun(MANUAL_MS); r.ok = 1; snprintf(r.text, sizeof r.text, "Washing started"); }
    Serial.printf("manual wash request: %s\n", r.text);
    linkSend(r);
    sendStatus();
  }
  if (millis() - lastStatus >= STATUS_MS) {
    lastStatus = millis();
    if (WiFi.status() == WL_CONNECTED) sendStatus();
  }
  if (!running && digitalRead(SETUP_BUTTON) == LOW) {
    delay(3000);
    if (digitalRead(SETUP_BUTTON) == LOW) wifiSetup(true);
  }
  if (!running && (!polledOnce || millis() - lastPoll >= POLL_MS)) {
    polledOnce = true;
    lastPoll = millis();
    if (WiFi.status() != WL_CONNECTED && !wifiReady() && ++wifiFails >= WIFI_FAILS_TO_PORTAL) {
      wifiFails = 0;
      wifiSetup(false);
    }
    if (WiFi.status() == WL_CONNECTED) wifiFails = 0;
    poll();
  }
  delay(20);
}
