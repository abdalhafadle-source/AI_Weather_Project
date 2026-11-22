// espnow_link.h - the radio link between the handheld (ESP32 + screen, the brain) and the panel controller
// (ESP32-C3 next to the pump, runs the relays). The SAME file is in esp32/pv_cleaner_client and esp32/pv_panel_c3:
// change both together.
//
// ESP-NOW = short messages straight from one ESP chip to another, no router in between.
//   handheld -> panel : HELLO every 2 s (the panel finds the handheld's radio channel by listening for it),
//                       RUN = "wash for N ms"
//   panel -> handheld : STATUS every 2 s (washing or not, time left, a fresh random number = nonce),
//                       RESULT = answer to a RUN
// Every message is signed with HMAC-SHA256 using ACK_KEY (secrets.h, never published). Old messages cannot be
// replayed: a RUN must carry the panel's current nonce, and a RESULT must echo the RUN's own random number.
#pragma once
#include <esp_now.h>
#include <esp_wifi.h>
#include <WiFi.h>
#include <mbedtls/md.h>
#include <string.h>

enum : uint8_t { LINK_HELLO = 1, LINK_RUN = 2, LINK_STATUS = 3, LINK_RESULT = 4 };

struct __attribute__((packed)) LinkMsg {
  uint8_t type;
  uint8_t running;   // STATUS: 1 = washing now
  uint8_t ok;        // RESULT: 1 = the wash started
  uint8_t pad;
  uint32_t seq;      // grows with every message from one sender
  uint32_t nonce;    // STATUS: the panel's current random number; RUN: copied from the last STATUS
  uint32_t req;      // RUN: a random number from the handheld; RESULT: the same number echoed back
  uint32_t ms;       // RUN: wash length; STATUS: time left
  uint32_t runMs;    // STATUS: length of the current wash
  char text[32];     // RESULT: reason
  uint8_t sig[32];   // HMAC-SHA256 of everything above
};

static const uint8_t LINK_BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static uint32_t linkSeq = 0;

static void linkSign(const LinkMsg& m, uint8_t out[32]) {
  mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), (const uint8_t*)ACK_KEY, strlen(ACK_KEY),
                  (const uint8_t*)&m, offsetof(LinkMsg, sig), out);
}

// true when the message has the right size and signature (freshness is checked by the caller: nonce / req)
static bool linkVerify(const uint8_t* data, int len, LinkMsg& m) {
  if (len != (int)sizeof(LinkMsg)) return false;
  memcpy(&m, data, sizeof m);
  uint8_t s[32];
  linkSign(m, s);
  uint8_t diff = 0;
  for (int i = 0; i < 32; i++) diff |= s[i] ^ m.sig[i];
  return diff == 0;
}

static bool linkSend(LinkMsg& m) {
  m.seq = ++linkSeq;
  linkSign(m, m.sig);
  return esp_now_send(LINK_BCAST, (const uint8_t*)&m, sizeof m) == ESP_OK;
}

// (re)start ESP-NOW on the current radio channel
static bool linkBegin(esp_now_recv_cb_t onRecv) {
  esp_now_deinit();
  if (esp_now_init() != ESP_OK) return false;
  esp_now_register_recv_cb(onRecv);
  esp_now_peer_info_t p = {};
  memcpy(p.peer_addr, LINK_BCAST, 6);
  p.channel = 0;  // = the current channel
  p.encrypt = false;
  return esp_now_add_peer(&p) == ESP_OK;
}
