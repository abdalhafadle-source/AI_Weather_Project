// pv_panel_c3.ino
// The panel controller (ESP32-C3 SuperMini, next to the pump). It only EXECUTES: the handheld (ESP32 with the
// screen) is the brain. It reads the server, applies all the limits and sends "wash for N ms" over ESP-NOW
// (espnow_link.h, signed with ACK_KEY). This board runs the pump and the brush and reports back. No Wi-Fi
// network and no internet are needed here: it listens on every radio channel until it hears the handheld.
//
// Board: ESP32C3 Dev Module, "USB CDC On Boot: Enabled" (FQBN esp32:esp32:esp32c3:CDCOnBoot=cdc).
// Wiring (2-channel relay module): PUMP -> GPIO 4, BRUSH -> GPIO 5, VCC 5V, GND. Most modules switch on LOW.
// secrets.h (copy secrets.example.h) must hold the SAME ACK_KEY as the handheld.
//
// One wash: pump on -> after PREWET_MS the brush starts -> RINSE_MS before the end the brush stops -> pump off.
// Safety here: relays OFF at boot; a wash never lasts longer than HARD_CAP_MS whatever it is told; a RUN is only
// accepted with a valid signature and the panel's current random number (an old message cannot be replayed);
// a wash already started finishes on time even if the handheld goes away.

#include <WiFi.h>
#include <esp_wifi.h>
#include "secrets.h"  // ACK_KEY
#ifndef ACK_KEY
#error "Add ACK_KEY to secrets.h (see secrets.example.h): the same key as on the handheld"
#endif
#include "espnow_link.h"

const int RELAY_PUMP = 4;    // change to your wiring
const int RELAY_BRUSH = 5;
const int RELAY_ON = LOW;    // most relay modules switch on LOW; use HIGH if yours is active-high

const unsigned long HARD_CAP_MS = 30UL * 60 * 1000;
const unsigned long PREWET_MS = 15UL * 1000;   // pump alone first: never brush a dry panel
const unsigned long RINSE_MS = 15UL * 1000;    // pump alone at the end: rinse the dust away
const unsigned long STATUS_MS = 2000;
const unsigned long LOST_MS = 20000;           // no HELLO for this long -> search the channels again
const unsigned long HOP_MS = 250;              // time on each channel while searching

unsigned long runStart = 0, runMs = 0, lastStatus = 0, lastHello = 0, lastHop = 0;
bool running = false, locked = false;
int channel = 1;
uint32_t nonce;

// the radio callback only copies; loop() acts
volatile bool rxHello = false, rxRun = false;
LinkMsg runMsg;
void onLink(const uint8_t* mac, const uint8_t* data, int len) {
  LinkMsg m;
  if (!linkVerify(data, len, m)) return;
  if (m.type == LINK_HELLO) rxHello = true;
  else if (m.type == LINK_RUN && !rxRun) { runMsg = m; rxRun = true; }
}

void pump(bool on) { digitalWrite(RELAY_PUMP, on ? RELAY_ON : !RELAY_ON); }
void brush(bool on) { digitalWrite(RELAY_BRUSH, on ? RELAY_ON : !RELAY_ON); }

void setChannel(int ch) {
  channel = ch;
  esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
}

void sendStatus() {
  LinkMsg m = {};
  m.type = LINK_STATUS;
  m.running = running;
  unsigned long e = millis() - runStart;
  m.ms = running && e < runMs ? runMs - e : 0;
  m.runMs = running ? runMs : 0;
  m.nonce = nonce;
  linkSend(m);
}

void handleRun(const LinkMsg& m) {
  LinkMsg r = {};
  r.type = LINK_RESULT;
  r.req = m.req;
  if (m.nonce != nonce) snprintf(r.text, sizeof r.text, "Old message, ignored");
  else if (running) snprintf(r.text, sizeof r.text, "Already washing");
  else if (m.ms == 0) snprintf(r.text, sizeof r.text, "Bad length");
  else {
    runMs = min((unsigned long)m.ms, HARD_CAP_MS);
    runStart = millis();
    running = true;
    pump(true);  // the brush follows after PREWET_MS
    r.ok = 1;
    snprintf(r.text, sizeof r.text, "Washing started");
    Serial.printf("WASH start for %lu s\n", runMs / 1000UL);
  }
  nonce = esp_random();  // a used (or wrong) number never works again
  linkSend(r);
  sendStatus();
}

void setup() {
  Serial.begin(115200);
  digitalWrite(RELAY_PUMP, !RELAY_ON);  // OFF level before enabling the pins
  digitalWrite(RELAY_BRUSH, !RELAY_ON);
  pinMode(RELAY_PUMP, OUTPUT);
  pinMode(RELAY_BRUSH, OUTPUT);
  nonce = esp_random();
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  setChannel(1);
  Serial.println(linkBegin(onLink) ? "ESP-NOW ready, searching for the handheld" : "ESP-NOW failed");
}

void loop() {
  if (running) {  // the wash sequence runs on time, whatever happens to the radio
    unsigned long e = millis() - runStart;
    brush(runMs > PREWET_MS + RINSE_MS && e >= PREWET_MS && e < runMs - RINSE_MS);
    if (e >= runMs) {
      brush(false);
      pump(false);
      running = false;
      Serial.println("WASH done");
      sendStatus();
    }
  }
  if (rxHello) {
    rxHello = false;
    lastHello = millis();
    if (!locked) Serial.printf("handheld found on channel %d\n", channel);
    locked = true;
  }
  if (rxRun) {
    LinkMsg m = runMsg;
    rxRun = false;
    handleRun(m);
  }
  if (locked && millis() - lastHello > LOST_MS) {
    locked = false;
    Serial.println("handheld lost -> searching");
  }
  if (!locked && millis() - lastHop >= HOP_MS) {  // listen on channels 1..13 in turn
    lastHop = millis();
    setChannel(channel % 13 + 1);
  }
  if (locked && millis() - lastStatus >= STATUS_MS) {
    lastStatus = millis();
    sendStatus();
  }
  delay(5);
}
