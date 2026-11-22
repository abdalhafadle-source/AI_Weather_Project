// espnow_link.h - the radio link between the panel controller (ESP32-C3, relays) and the handheld screen.
// The SAME file is in esp32/pv_panel_c3 and esp32/pv_cleaner_client: change both together.
//
// ESP-NOW = short messages straight from one ESP chip to another, no router in between. Both devices are also on
// the home Wi-Fi, which puts them on the same radio channel (ESP-NOW needs that).
// Every message is broadcast and signed with HMAC-SHA256 using ACK_KEY (secrets.h, never published): a message
// with a wrong signature, an old time stamp or a repeated number is ignored, so nobody else can start the pump.
#pragma once
#include <esp_now.h>
#include <WiFi.h>
#include <mbedtls/md.h>
#include <string.h>
#include <time.h>

enum : uint8_t { LINK_STATUS = 1, LINK_WASH_REQ = 2, LINK_WASH_RESULT = 3 };

struct __attribute__((packed)) LinkMsg {
  uint8_t type;
  uint8_t running;       // STATUS: 1 = washing now
  uint8_t countToday;    // STATUS: washes today (auto + manual)
  uint8_t ok;            // WASH_RESULT: 1 = started
  uint32_t ts;           // sender's clock (UTC seconds); messages older than 60 s are ignored
  uint32_t seq;          // grows with every message from one sender
  uint32_t leftMs;       // STATUS: time left in the current wash
  uint32_t runMs;        // STATUS: length of the current wash
  int64_t lastRun;       // STATUS: start of the last wash (UTC seconds), 0 = never
  char text[40];         // WASH_RESULT: reason, shown on the screen
  uint8_t sig[32];       // HMAC-SHA256 of everything above
};

static const uint8_t LINK_BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static uint32_t linkSeq = 0;

static void linkSign(const LinkMsg& m, uint8_t out[32]) {
  mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), (const uint8_t*)ACK_KEY, strlen(ACK_KEY),
                  (const uint8_t*)&m, offsetof(LinkMsg, sig), out);
}

// true when the signature is right and the message is fresh (not older than 60 s, not repeated)
static bool linkCheck(const uint8_t* data, int len, LinkMsg& m, uint32_t& lastSeq, uint32_t& lastTs) {
  if (len != (int)sizeof(LinkMsg)) return false;
  memcpy(&m, data, sizeof m);
  uint8_t s[32];
  linkSign(m, s);
  uint8_t diff = 0;
  for (int i = 0; i < 32; i++) diff |= s[i] ^ m.sig[i];
  if (diff) return false;
  time_t now = time(nullptr);
  if (now < 1700000000 || labs((long)now - (long)m.ts) > 60) return false;   // needs a synced clock
  if (m.ts < lastTs || (m.ts == lastTs && m.seq <= lastSeq)) return false;   // replayed
  lastTs = m.ts;
  lastSeq = m.seq;
  return true;
}

static bool linkSend(LinkMsg& m) {
  m.ts = (uint32_t)time(nullptr);
  m.seq = ++linkSeq;
  linkSign(m, m.sig);
  return esp_now_send(LINK_BCAST, (const uint8_t*)&m, sizeof m) == ESP_OK;
}

// call after Wi-Fi is connected (the radio channel is then fixed by the router)
static bool linkBegin(esp_now_recv_cb_t onRecv) {
  esp_now_deinit();
  if (esp_now_init() != ESP_OK) return false;
  esp_now_register_recv_cb(onRecv);
  esp_now_peer_info_t p = {};
  memcpy(p.peer_addr, LINK_BCAST, 6);
  p.channel = 0;  // = the current Wi-Fi channel
  p.encrypt = false;
  return esp_now_add_peer(&p) == ESP_OK;
}
