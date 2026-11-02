// pv_cleaner_client.ino
// ESP32 side of the Hilla PV-cleaning AI: every 14 min read the command that our VPS writes
// every hour, and when it says "clean" (with a command_id not run before) switch the brush + pump relays on.
//
// Board: ESP32 (Arduino core). Library: ArduinoJson v7 (Arduino IDE -> Library Manager).
// Put your Wi-Fi name/password in secrets.h (copy secrets.example.h). secrets.h is never published.
//
// Safety, all enforced here on the ESP32 itself:
//   - no answer / bad answer / no Wi-Fi  -> do nothing
//   - clock not synced yet (NTP) or command past valid_until -> do nothing
//   - same command_id is never run twice (saved in flash, survives a reboot)
//   - a run never lasts longer than HARD_CAP_MS (30 min), whatever the command says
//   - at most 2 runs per day and 6 h between runs, even if the command file says otherwise
//   - all relays OFF at boot

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include "ArduinoJson-v7.4.3.h"  // bundled single-file ArduinoJson (MIT): works even if the libraries folder path has non-English letters
#include <time.h>
#include "secrets.h"  // WIFI_SSID, WIFI_PASS

const char* COMMAND_URL = "http://64.226.106.240/command";  // our VPS (https:// also works)

const int RELAY_BRUSH = 26;  // change to your wiring
const int RELAY_PUMP = 27;
const int RELAY_ON = LOW;    // most relay modules switch on LOW; use HIGH if yours is active-high

const unsigned long POLL_MS = 14UL * 60 * 1000;         // a new command appears once per hour
const unsigned long CLEAN_CYCLE_MS = 30UL * 60 * 1000;  // your normal cleaning cycle length
const unsigned long HARD_CAP_MS = 30UL * 60 * 1000;     // absolute maximum run time
const long MIN_GAP_S = 6L * 3600;  // same caps as decision.py, enforced here too in case the command
const int MAX_PER_DAY = 2;         // file is ever wrong or tampered with

Preferences prefs;
unsigned long lastPoll = 0, runStart = 0, runMs = 0;
bool running = false, polledOnce = false;

void relays(bool on) {
  digitalWrite(RELAY_BRUSH, on ? RELAY_ON : !RELAY_ON);
  digitalWrite(RELAY_PUMP, on ? RELAY_ON : !RELAY_ON);
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
  return WiFi.status() == WL_CONNECTED;
}

bool fetchCommand(JsonDocument& doc) {
  if (!wifiReady()) return false;
  WiFiClient plain;
  WiFiClientSecure tls;
  tls.setInsecure();  // shortcut: HTTPS without certificate check; add the server's root CA to harden
  WiFiClient& client = strncmp(COMMAND_URL, "https", 5) == 0 ? static_cast<WiFiClient&>(tls) : plain;
  HTTPClient http;
  http.setConnectTimeout(30000);
  http.setTimeout(30000);
  if (!http.begin(client, COMMAND_URL)) return false;
  int code = http.GET();
  bool ok = code == 200 && deserializeJson(doc, http.getString()) == DeserializationError::Ok;
  http.end();
  return ok;
}

void poll() {
  JsonDocument doc;
  bool ok = fetchCommand(doc);
  if (!ok) {  // one retry for a short network hiccup
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
  long long until = isoToEpoch(doc["valid_until"] | "");
  time_t now = time(nullptr);
  if (now < 1700000000 || until < 0 || (long long)now > until) {  // clock not synced, unreadable, or expired
    Serial.println("clean command expired or clock not set -> do nothing");
    return;
  }
  if (prefs.getString("last_id", "") == id) return;  // this command was already executed
  long today = (long)((now + 3 * 3600) / 86400);       // Baghdad calendar day
  int countToday = prefs.getLong("day", -1) == today ? prefs.getInt("count", 0) : 0;
  if ((long long)now - prefs.getLong64("last_run", 0) < MIN_GAP_S || countToday >= MAX_PER_DAY) {
    Serial.println("local safety cap (6 h gap / 2 per day) -> do nothing");
    return;
  }
  prefs.putString("last_id", id);  // save first, so a reboot mid-run never repeats it
  prefs.putLong64("last_run", (int64_t)now);
  prefs.putLong("day", today);
  prefs.putInt("count", countToday + 1);

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
  configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC clock from the internet (free)
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
