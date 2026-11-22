// pv_cleaner_client.ino
// The HANDHELD screen of the Hilla PV-cleaning AI (since 2026-11-22). It no longer drives any relay: the panel
// controller (esp32/pv_panel_c3, ESP32-C3 next to the pump) reads the server and runs the pump and the brush.
// This device shows the command, the forecast and the panel's state (ESP-NOW status every 3 s, espnow_link.h),
// and "Wash now" asks the panel for a 1-minute wash; the panel checks its own limits and answers.
//
// Board: ESP32 (Arduino core). Libraries are bundled in this folder (ArduinoJson, WiFiManager by tzapu, MIT).
// Screen: 3.5" 480x320 touch screen (ILI9488 + XPT2046) drawn by ui.h with LovyanGFX 1.3.0, which lives in
// esp32/libraries (not in git): arduino-cli lib download LovyanGFX, then unzip it there. Wiring (SPI, VSPI):
//   (carrier board cad/pcb) screen: SCK 16, MOSI 4, CS 15, DC 2, RESET + LED + VCC on 3V3, SDO not connected
//   touch (own bus): T_CLK 17, T_DIN 18, T_DO 19, T_CS 5, T_IRQ 21
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
//   - a run never lasts longer than HARD_CAP_MS (30 min), whatever the command says
//   - at most 2 runs per day and 6 h between runs, even if the command file says otherwise
//   - all relays OFF at boot
//   (washing safety now lives on the panel controller; this screen never switches anything itself)

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
const char* PORTAL_NAME = "Hilla-PV-Setup";  // the ESP32's own network for Wi-Fi setup
const int PORTAL_S = 180;                    // setup network stays open 3 min, then it tries again later
const int SETUP_BUTTON = 0;                  // BOOT button (GPIO0): hold 3 s to open the setup network
const int WIFI_FAILS_TO_PORTAL = 3;          // polls in a row without Wi-Fi (~42 min) -> open the setup network

const unsigned long POLL_MS = 14UL * 60 * 1000;         // a new command appears once per hour
const long MIN_GAP_S = 6L * 3600;  // the panel's limits, shown on the screen
const int MAX_PER_DAY = 2;
const unsigned long PANEL_LOST_MS = 15000;  // no status from the panel for this long -> "offline"

Preferences prefs;
unsigned long lastPoll = 0, runStart = 0, runMs = 0;
bool running = false, polledOnce = false;
int wifiFails = 0;
// panel state from its ESP-NOW status (the radio callback only copies; loop() applies it)
bool panelOnline = false;
unsigned long panelSeenMs = 0;
int panelCount = 0;
long long panelLastRun = 0;
volatile bool rxStatus = false, rxResult = false;
LinkMsg rxMsg, rxRes;
uint32_t rxSeq = 0, rxTs = 0;
void onLink(const uint8_t* mac, const uint8_t* data, int len) {
  LinkMsg m;
  if (!linkCheck(data, len, m, rxSeq, rxTs)) return;
  if (m.type == LINK_STATUS) { rxMsg = m; rxStatus = true; }
  else if (m.type == LINK_WASH_RESULT) { rxRes = m; rxResult = true; }
}
#include "ui.h"  // touch screen: needs the globals above

// connect to the saved network; if that fails, open the setup network for PORTAL_S seconds (relays stay OFF:
// only called while not cleaning). force = open the setup network even if the saved one works.
void wifiSetup(bool force) {
  WiFiManager wm;
  wm.setConfigPortalTimeout(PORTAL_S);
  wm.setConnectTimeout(20);
  uiWifiScreen(force);
  Serial.printf("Wi-Fi setup: if no network, join \"%s\" from a phone\n", PORTAL_NAME);
  bool ok = force ? wm.startConfigPortal(PORTAL_NAME, PORTAL_PASS) : wm.autoConnect(PORTAL_NAME, PORTAL_PASS);
  Serial.println(ok ? "Wi-Fi connected" : "Wi-Fi setup timed out -> will try again later");
  if (ok) Serial.println(linkBegin(onLink) ? "ESP-NOW ready" : "ESP-NOW failed");
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
  WiFiClient plain;
  WiFiClientSecure tls;
  tls.setCACert(ROOT_CAS);  // accept only a server with a valid Let's Encrypt certificate
  WiFiClient& client = strncmp(COMMAND_URL, "https", 5) == 0 ? static_cast<WiFiClient&>(tls) : plain;
  HTTPClient http;
  http.setConnectTimeout(30000);
  http.setTimeout(30000);
  if (!http.begin(client, COMMAND_URL)) return false;
  http.setUserAgent("HillaPV-Screen");  // not "ESP32": the server counts only the panel controller as the device
  int code = http.GET();
  bool ok = code == 200 && deserializeJson(doc, http.getString()) == DeserializationError::Ok;
  http.end();
  return ok;
}

// read the command for the screen only: the panel controller runs it
void poll() {
  JsonDocument doc;
  bool ok = fetchCommand(doc);
  if (!ok) {  // one retry for a short network hiccup
    delay(30000);
    ok = fetchCommand(doc);
  }
  if (!ok) {
    uiPollResult(false);
    Serial.println("no command");
    return;
  }
  uiStoreCommand(doc);
  Serial.printf("action=%s id=%s reason=%s\n", doc["action"] | "wait", doc["command_id"] | "", doc["reason"] | "");
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

void loop() {
  if (rxStatus) {  // the panel's state: washing or not, time left, washes today
    rxStatus = false;
    LinkMsg m = rxMsg;
    panelOnline = true;
    panelSeenMs = millis();
    panelCount = m.countToday;
    panelLastRun = m.lastRun;
    running = m.running;
    if (running) { runMs = m.runMs; runStart = millis() - (m.runMs - m.leftMs); }
  }
  if (rxResult) { rxResult = false; uiWashResult(rxRes.ok, rxRes.text); }
  if (panelOnline && millis() - panelSeenMs > PANEL_LOST_MS) { panelOnline = false; running = false; }
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
