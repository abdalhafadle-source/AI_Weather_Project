// espnow_link.h - the radio link between the handheld (ESP32 + screen, the brain) and the panel controller
// (ESP32-C3 next to the pump, runs the relays). The SAME file is in esp32/pv_cleaner_client and esp32/pv_panel_c3:
// change both together.
//
// ESP-NOW = short messages straight from one ESP chip to another, no router in between.
//   handheld -> panel : HELLO every second (the panel finds the handheld's radio channel by it),
//                       RUN = "wash for N ms",
//                       WIFI = the handheld's Wi-Fi name and password, ENCRYPTED, so the panel joins the same
//                       network by itself (both radios then stay on the router's channel)
//   panel -> handheld : STATUS every 2 s (washing or not, time left, a fresh random number = nonce, which network
//                       it has, as a keyed fingerprint), RESULT = answer to a RUN
// Every message is signed with HMAC-SHA256 using ACK_KEY (secrets.h, never published). Old messages cannot be
// replayed: RUN and WIFI must carry the panel's current nonce, and a RESULT must echo the RUN's own random number.
#pragma once
#include <esp_now.h>
#include <esp_wifi.h>
#include <WiFi.h>
#include <mbedtls/md.h>
#include <mbedtls/aes.h>
#include <string.h>

enum : uint8_t { LINK_HELLO = 1, LINK_RUN = 2, LINK_STATUS = 3, LINK_RESULT = 4, LINK_WIFI = 5 };

struct __attribute__((packed)) LinkMsg {
  uint8_t type;
  uint8_t running;   // STATUS: 1 = washing now
  uint8_t ok;        // RESULT: 1 = the wash started
  uint8_t wifi;      // STATUS: 1 = the panel is on Wi-Fi
  uint32_t seq;      // grows with every message from one sender
  uint32_t nonce;    // STATUS: the panel's current random number; RUN / WIFI: copied from the last STATUS
  uint32_t req;      // RUN / WIFI: a random number from the handheld; RESULT: the same number echoed back
  uint32_t ms;       // RUN: wash length; STATUS: time left
  uint32_t runMs;    // STATUS: length of the current wash
  uint32_t net;      // STATUS: fingerprint of the panel's saved network (linkNetHash)
  char text[32];     // RESULT: reason
  char cred[98];     // WIFI: name (33) + password (65), encrypted with linkCrypt
  uint8_t sig[32];   // HMAC-SHA256 of everything above
};

static const uint8_t LINK_BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static uint32_t linkSeq = 0;

static void linkHmac(const uint8_t* data, size_t n, uint8_t out[32]) {
  mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), (const uint8_t*)ACK_KEY, strlen(ACK_KEY), data, n, out);
}
static void linkSign(const LinkMsg& m, uint8_t out[32]) { linkHmac((const uint8_t*)&m, offsetof(LinkMsg, sig), out); }

// keyed fingerprint of a network (name + password): equal on both sides when they use the same network,
// and tells nothing about the password to anyone without ACK_KEY
static uint32_t linkNetHash(const char* ssid, const char* pass) {
  if (!ssid || !ssid[0]) return 0;
  uint8_t buf[100] = {}, h[32];
  strncpy((char*)buf, ssid, 33);
  strncpy((char*)buf + 34, pass ? pass : "", 65);
  linkHmac(buf, sizeof buf, h);
  uint32_t v;
  memcpy(&v, h, 4);
  return v ? v : 1;
}

// AES-128-CTR on m.cred (same call encrypts and decrypts); key from ACK_KEY, counter from seq + req
static void linkCrypt(LinkMsg& m) {
  uint8_t k[32], ctr[16] = {}, stream[16];
  const char tag[] = "wifi-cred";
  linkHmac((const uint8_t*)tag, sizeof tag - 1, k);
  memcpy(ctr, &m.req, 4);
  memcpy(ctr + 4, &m.nonce, 4);
  size_t off = 0;
  mbedtls_aes_context a;
  mbedtls_aes_init(&a);
  mbedtls_aes_setkey_enc(&a, k, 128);
  mbedtls_aes_crypt_ctr(&a, sizeof m.cred, &off, ctr, stream, (const uint8_t*)m.cred, (uint8_t*)m.cred);
  mbedtls_aes_free(&a);
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
