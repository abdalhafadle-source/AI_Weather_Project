// pv_cleaner_client.ino
// The handheld of the Hilla PV-cleaning AI (ESP32 + touch screen): THE BRAIN. Every 14 min it reads the command
// that our VPS writes every hour; when it says "clean" (with a command_id not run before) it tells the panel
// controller (esp32/pv_panel_c3, ESP32-C3 next to the pump) to wash, over ESP-NOW (espnow_link.h, signed with
// ACK_KEY). The panel runs the pump and then the brush and answers; only after that answer is the wash counted
// and the server told (POST /ack). If the panel does not answer, nothing is saved and the next poll tries again.
// The panel needs no Wi-Fi setup of its own: this device sends it its network name and password (encrypted)
// whenever the panel has none or a different one, so both stay on the same network and radio channel.
//
// Board: ESP32 (Arduino core). Libraries are bundled in this folder (ArduinoJson, WiFiManager by tzapu, MIT).
// Screen: 3.5" 480x320 touch screen (ILI9488 + XPT2046) drawn by ui.h with LovyanGFX 1.3.0, which lives in
// esp32/libraries (not in git): arduino-cli lib download LovyanGFX, then unzip it there. Wiring: see ui.h
// (PINS_BREADBOARD switch: breadboard now, carrier board cad/pcb later).
// First start (or finger held on the screen for the first 3 s): "Touch the arrows to calibrate", saved in flash.
// Wi-Fi is set from a phone, no re-upload needed (WiFiManager): when the saved network is not reachable, the
// ESP32 opens its own network "Hilla-PV-Setup" (password PORTAL_PASS in secrets.h) for 3 minutes; join it,
// pick the new network and type its password. Hold the BOOT button 3 s to open it on purpose.
// secrets.h (copy secrets.example.h) holds ACK_KEY and PORTAL_PASS and is never published.
//
// Safety, all enforced here on the ESP32 itself:
//   - no answer / bad answer / no Wi-Fi  -> do nothing
//   - clock not synced yet (NTP) or command past valid_until -> do nothing
//   - same command_id is never run twice (saved in flash, survives a reboot)
//   - a run never lasts longer than HARD_CAP_MS (30 min), whatever the command says (the panel caps it too)
//   - at most 2 runs per day and 6 h between runs, even if the command file says otherwise

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include "ArduinoJson-v7.4.3.h"  // bundled single-file ArduinoJson (MIT): works even if the libraries folder path has non-English letters
#include <time.h>
#include "WiFiManager.h"  // bundled WiFiManager 2.0.17 (MIT, see WiFiManager-LICENSE.txt)
#include "secrets.h"  // ACK_KEY, PORTAL_PASS
#ifndef ACK_KEY
#error "Add ACK_KEY to secrets.h (see secrets.example.h): the same key as on the server"
#endif
#ifndef PORTAL_PASS
#error "Add PORTAL_PASS to secrets.h (see secrets.example.h): password of the Wi-Fi setup network, 8+ characters"
#endif
#include "root_ca.h"  // ROOT_CAS: Let's Encrypt roots, to check the server's identity
#include "espnow_link.h"  // signed radio messages to/from the panel controller

const char* COMMAND_URL = "https://hilla-ai.duckdns.org/command";  // our VPS, encrypted
const char* ACK_URL = "https://hilla-ai.duckdns.org/ack";
const char* PORTAL_NAME = "Hilla-PV-Setup";  // the ESP32's own network for Wi-Fi setup
const int PORTAL_S = 180;                    // setup network stays open 3 min, then it tries again later
const int SETUP_BUTTON = 0;                  // BOOT button (GPIO0): hold 3 s to open the setup network
const int WIFI_FAILS_TO_PORTAL = 3;          // polls in a row without Wi-Fi (~42 min) -> open the setup network

const unsigned long POLL_MS = 14UL * 60 * 1000;         // a new command appears once per hour
const unsigned long CLEAN_CYCLE_MS = 30UL * 60 * 1000;  // your normal cleaning cycle length
const unsigned long HARD_CAP_MS = 30UL * 60 * 1000;     // absolute maximum run time
const long MIN_GAP_S = 6L * 3600;  // same caps as decision.py, enforced here too in case the command
const int MAX_PER_DAY = 2;         // file is ever wrong or tampered with
const unsigned long HELLO_MS = 1000;        // heartbeat to the panel (it finds our radio channel by it)
const unsigned long PANEL_LOST_MS = 30000;  // no status from the panel for this long -> "offline"

Preferences prefs;
unsigned long lastPoll = 0, runStart = 0, runMs = 0, lastHello = 0;
bool running = false, polledOnce = false;
int wifiFails = 0;

// panel controller state, from its STATUS messages (the radio callback only copies; loop() applies it)
bool panelOnline = false;
unsigned long panelSeenMs = 0;
uint32_t panelNonce = 0, panelNet = 0;
unsigned long lastWifiShare = 0;
volatile bool rxStatus = false, rxResult = false;
LinkMsg rxMsg, rxRes;
void onLink(const uint8_t* mac, const uint8_t* data, int len) {
  LinkMsg m;
  if (!linkVerify(data, len, m)) return;
  if (m.type == LINK_STATUS) { rxMsg = m; rxStatus = true; }
  else if (m.type == LINK_RESULT) { rxRes = m; rxResult = true; }
}
void applyStatus() {
  if (!rxStatus) return;
  rxStatus = false;
  LinkMsg m = rxMsg;
  panelOnline = true;
  panelSeenMs = millis();
  panelNonce = m.nonce;
  panelNet = m.net;
  running = m.running;
  if (running) { runMs = m.runMs; runStart = millis() - (m.runMs - m.ms); }
}

// ask the panel to wash for ms; waits up to ~3 s for its answer. why = reason when it did not start.
bool panelRun(unsigned long ms, char* why, size_t n) {
  applyStatus();
  if (!panelOnline) { snprintf(why, n, "Panel controller offline"); return false; }
  for (int attempt = 0; attempt < 2; attempt++) {
    LinkMsg m = {};
    m.type = LINK_RUN;
    m.nonce = panelNonce;
    m.req = esp_random();
    m.ms = min(ms, HARD_CAP_MS);
    rxResult = false;
    linkSend(m);
    for (int i = 0; i < 75; i++) {  // 1.5 s
      delay(20);
      if (rxResult && rxRes.req == m.req) {
        rxResult = false;
        snprintf(why, n, "%s", rxRes.text);
        if (rxRes.ok) { running = true; runMs = m.ms; runStart = millis(); }
        return rxRes.ok;
      }
    }
    applyStatus();  // a fresh nonce may have arrived: try once more with it
  }
  snprintf(why, n, "No answer from the panel");
  return false;
}

#include "ui.h"  // touch screen: needs the globals above

// connect to the saved network; if that fails, open the setup network for PORTAL_S seconds
// (only called while not cleaning). force = open the setup network even if the saved one works.
void wifiSetup(bool force) {
  WiFiManager wm;
  wm.setConfigPortalTimeout(PORTAL_S);
  wm.setConnectTimeout(20);
  uiWifiScreen(force);
  Serial.printf("Wi-Fi setup: if no network, join \"%s\" from a phone\n", PORTAL_NAME);
  bool ok = force ? wm.startConfigPortal(PORTAL_NAME, PORTAL_PASS) : wm.autoConnect(PORTAL_NAME, PORTAL_PASS);
  Serial.println(ok ? "Wi-Fi connected" : "Wi-Fi setup timed out -> will try again later");
  WiFi.setSleep(false);  // power saving makes the radio miss ESP-NOW messages from the panel
  Serial.println(linkBegin(onLink) ? "ESP-NOW ready" : "ESP-NOW failed");  // on the (new) radio channel
  uiWifiDone();
}

// "2026-10-29T15:00:00+03:00" -> seconds since 1970 UTC (days-from-civil); -1 if unreadable
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
  // a certificate can only be checked with a correct clock: wait up to 15 s for the internet time (NTP)
  for (int i = 0; i < 30 && time(nullptr) < 1700000000; i++) delay(500);
  WiFiClientSecure tls;
  tls.setCACert(ROOT_CAS);  // accept only a server with a valid Let's Encrypt certificate
  HTTPClient http;
  http.setConnectTimeout(30000);
  http.setTimeout(30000);
  if (!http.begin(tls, COMMAND_URL)) return false;
  http.addHeader("X-Key", ACK_KEY);                             // proves it is our ESP32
  http.addHeader("X-Last-Id", prefs.getString("last_id", ""));  // the last command we really ran (backup if an ack got lost)
  int code = http.GET();
  bool ok = code == 200 && deserializeJson(doc, http.getString()) == DeserializationError::Ok;
  http.end();
  return ok;
}

// tell the server this command really started; a failure here never stops the wash
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

// the local limits (auto and manual washes together); returns the reason when not allowed, or nullptr
const char* washBlocked() {
  time_t now = time(nullptr);
  if (running) return "Already washing";
  if (now < 1700000000) return "Clock not set yet";
  long today = (long)((now + 3 * 3600) / 86400);  // Baghdad calendar day
  int countToday = prefs.getLong("day", -1) == today ? prefs.getInt("count", 0) : 0;
  if ((long long)now - prefs.getLong64("last_run", 0) < MIN_GAP_S || countToday >= MAX_PER_DAY)
    return "Limit reached (6 h gap / 2 per day)";
  return nullptr;
}
void countWash() {
  time_t now = time(nullptr);
  long today = (long)((now + 3 * 3600) / 86400);
  int countToday = prefs.getLong("day", -1) == today ? prefs.getInt("count", 0) : 0;
  prefs.putLong64("last_run", (int64_t)now);
  prefs.putLong("day", today);
  prefs.putInt("count", countToday + 1);
}

void poll() {
  JsonDocument doc;
  bool ok = fetchCommand(doc);
  if (!ok) {  // one retry for a short network hiccup
    delay(30000);
    ok = fetchCommand(doc);
  }
  if (!ok) {
    uiPollResult(false);
    Serial.println("no command -> do nothing");
    return;
  }
  uiStoreCommand(doc);
  const char* action = doc["action"] | "wait";
  const char* id = doc["command_id"] | "";
  const char* reason = doc["reason"] | "";
  Serial.printf("action=%s id=%s reason=%s\n", action, id, reason);

  if (strcmp(action, "clean") != 0 || id[0] == '\0') return;
  long long until = isoToEpoch(doc["valid_until"] | "");
  time_t now = time(nullptr);
  if (now < 1700000000 || until < 0 || (long long)now > until) {  // clock not synced, unreadable, or expired
    Serial.println("clean command expired or clock not set -> do nothing");
    return;
  }
  if (prefs.getString("last_id", "") == id) return;  // this command was already executed
  const char* why = washBlocked();
  if (why) {
    Serial.printf("local safety cap: %s -> do nothing\n", why);
    return;
  }
  unsigned long serverMax = (unsigned long)(doc["max_duration_min"] | 30) * 60000UL;
  char ans[40];
  if (!panelRun(min(CLEAN_CYCLE_MS, min(serverMax, HARD_CAP_MS)), ans, sizeof ans)) {
    Serial.printf("panel did not start (%s) -> next poll tries again\n", ans);
    return;  // nothing saved: the same command is tried again while it is valid
  }
  prefs.putString("last_id", id);
  countWash();
  Serial.printf("CLEAN started on the panel for %lu min\n", runMs / 60000UL);
  sendAck(id);
}

// poll with "Updating..." on the screen, then the extra status request (forecast bars) for the screen
void pollNow() {
  polledOnce = true;
  lastPoll = millis();
  uiBusy(true);
  poll();
  uiAfterPoll();
  uiBusy(false);
}

void setup() {
  Serial.begin(115200);
  prefs.begin("pvclean", false);
  pinMode(SETUP_BUTTON, INPUT_PULLUP);
  uiBegin();
  WiFi.mode(WIFI_STA);
  wifiSetup(false);  // saved network, or the setup network for 3 min
  configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC clock from the internet (free)
}

// give the panel our Wi-Fi (encrypted) when it has none or another one; at most every 20 s
void shareWifi() {
  if (!panelOnline || running || WiFi.status() != WL_CONNECTED || millis() - lastWifiShare < 20000) return;
  String ssid = WiFi.SSID(), pass = WiFi.psk();
  if (panelNet == linkNetHash(ssid.c_str(), pass.c_str())) return;
  lastWifiShare = millis();
  LinkMsg m = {};
  m.type = LINK_WIFI;
  m.nonce = panelNonce;
  m.req = esp_random();
  strlcpy(m.cred, ssid.c_str(), 33);
  strlcpy(m.cred + 33, pass.c_str(), 65);
  linkCrypt(m);  // encrypt
  linkSend(m);
  Serial.println("Wi-Fi sent to the panel");
}

void loop() {
  applyStatus();
  shareWifi();
  if (panelOnline && millis() - panelSeenMs > PANEL_LOST_MS) panelOnline = false;
  if (running && millis() - runStart >= runMs + 3000) running = false;  // panel gone mid-wash: it still stops on its own
  if (millis() - lastHello >= HELLO_MS) {
    lastHello = millis();
    LinkMsg m = {};
    m.type = LINK_HELLO;
    linkSend(m);
  }
  if (!running && digitalRead(SETUP_BUTTON) == LOW) {  // BOOT held 3 s -> Wi-Fi setup network
    delay(3000);
    if (digitalRead(SETUP_BUTTON) == LOW) wifiSetup(true);
  }
  if (!running && (!polledOnce || millis() - lastPoll >= POLL_MS)) {
    polledOnce = true;
    lastPoll = millis();
    if (WiFi.status() != WL_CONNECTED && !wifiReady() && ++wifiFails >= WIFI_FAILS_TO_PORTAL) {
      wifiFails = 0;
      wifiSetup(false);  // network changed or gone: let the owner pick a new one from a phone
    }
    if (WiFi.status() == WL_CONNECTED) wifiFails = 0;
    pollNow();
  }
  uiTick();  // touch every ~20 ms, small redraw once a second
  delay(20);
}
