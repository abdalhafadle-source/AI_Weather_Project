// ui.h - touch screen for the Hilla PV cleaner (3.5" ILI9488 320x480 portrait + XPT2046 touch), LovyanGFX.
// Included once by pv_cleaner_client.ino, after its globals (prefs, running, runStart, runMs, lastPoll, polledOnce).
// The screen only shows data and can start a 1-minute manual wash under the SAME local limits (6 h gap, 2 per day).
// Nothing here changes the safety rules; the relay stop-on-time logic stays in loop() of the .ino.
#pragma once
#include <LovyanGFX.hpp>
#include "fonts_inter.h"

void wifiSetup(bool force);
void pollNow();
const char* washBlocked();
void countWash();
long long isoToEpoch(const char* s);

// ---------- hardware: which wiring? 1 = breadboard (now), 0 = carrier board cad/pcb (after it is built) ----------
// breadboard: screen and touch share VSPI (SCK 18, MOSI 23, MISO 19), CS 15, DC 2, RESET 4, T_CS 5, T_IRQ 34.
// carrier board: screen on VSPI (CS 15, DC 2, MOSI 4, SCK 16, RESET on 3V3 = software reset), touch on its own
// HSPI bus (T_CLK 17, T_CS 5, T_DIN 18, T_DO 19, T_IRQ 21), so the single-sided board needs no jumper wires.
#define PINS_BREADBOARD 1
#if PINS_BREADBOARD
#define P_SCLK 18
#define P_MOSI 23
#define P_MISO 19
#define P_RST 4
#define P_FREQ 27000000
#define P_SHARED true
#define T_HOST SPI3_HOST
#define T_SCLK 18
#define T_MOSI 23
#define T_IRQ 34
#else
#define P_SCLK 16
#define P_MOSI 4
#define P_MISO -1
#define P_RST -1
#define P_FREQ 20000000
#define P_SHARED false
#define T_HOST SPI2_HOST
#define T_SCLK 17
#define T_MOSI 18
#define T_IRQ 21
#endif
class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ILI9488 _panel;
  lgfx::Bus_SPI _bus;
  lgfx::Touch_XPT2046 _touch;
public:
  LGFX() {
    {
      auto c = _bus.config();
      c.spi_host = SPI3_HOST;
      c.spi_mode = 0;
      c.freq_write = P_FREQ;
      c.freq_read = 16000000;
      c.spi_3wire = false;      // screen SDO is not wired
      c.use_lock = true;
      c.dma_channel = SPI_DMA_CH_AUTO;
      c.pin_sclk = P_SCLK;
      c.pin_mosi = P_MOSI;
      c.pin_miso = P_MISO;
      c.pin_dc = 2;
      _bus.config(c);
      _panel.setBus(&_bus);
    }
    {
      auto c = _panel.config();
      c.pin_cs = 15;
      c.pin_rst = P_RST;
      c.pin_busy = -1;
      c.panel_width = 320;
      c.panel_height = 480;
      c.offset_x = 0;
      c.offset_y = 0;
      c.readable = false;
      c.invert = false;
      c.rgb_order = false;
      c.dlen_16bit = false;
      c.bus_shared = P_SHARED;
      _panel.config(c);
    }
    {
      auto c = _touch.config();
      c.x_min = 300;
      c.x_max = 3900;
      c.y_min = 300;
      c.y_max = 3900;
      c.pin_int = T_IRQ;
      c.bus_shared = P_SHARED;
      c.offset_rotation = 0;
      c.spi_host = T_HOST;
      c.freq = 1000000;
      c.pin_sclk = T_SCLK;
      c.pin_mosi = T_MOSI;
      c.pin_miso = 19;
      c.pin_cs = 5;
      _touch.config(c);
      _panel.setTouch(&_touch);
    }
    setPanel(&_panel);
  }
};
static LGFX tft;

// ---------- data shown on screen ----------
struct UiCmd {
  bool ok = false, everOk = false;  // last poll worked / any poll worked
  uint32_t okMs = 0;                // millis() of the last good poll
  char action[8] = "", reason[48] = "", pending[40] = "", routineDue[28] = "";
  float pRain = -1, pDust = -1, thRain = -1, thDust = -1, pm10 = -1;
} uc;
struct UiHour { uint8_t hour, day; float r, d; };
static UiHour fch[24];
static int fcN = 0;
static float fcTemp = NAN;
static char lastClean[28] = "";
bool uiStatusPending = false;  // status request postponed until a wash ends

// ---------- look ----------
// colours: dark (night) or light (day) theme, chosen on the Device tab and saved in flash ("light")
static uint32_t C_BG, C_CARD, C_LINE, C_FG, C_DIM, C_OK, C_RAIN, C_DUST, C_BAD, C_TRACK, C_NAV, C_DARK, C_HI;
static bool uiLight = false;
static void applyTheme(bool light) {
  uiLight = light;
  static const uint32_t D[] = {0x0b1018, 0x141c27, 0x223042, 0xe8eef4, 0x8696a8, 0x3ddc97, 0x4aa8ff, 0xf2b544, 0xff6b6b, 0x1c2736, 0x0e1520, 0x06261a, 0x1a2635};
  static const uint32_t L[] = {0xf3f5f8, 0xffffff, 0xd3dae3, 0x111a24, 0x56677a, 0x168a57, 0x1f6fc4, 0xb57900, 0xd32f2f, 0xe2e7ee, 0xe8ecf1, 0xffffff, 0xdce5ef};
  const uint32_t* c = light ? L : D;
  uint32_t* v[] = {&C_BG, &C_CARD, &C_LINE, &C_FG, &C_DIM, &C_OK, &C_RAIN, &C_DUST, &C_BAD, &C_TRACK, &C_NAV, &C_DARK, &C_HI};
  for (int i = 0; i < 13; i++) *v[i] = c[i];
}
#define F9 (&fonts::FreeSans9pt7b)
#define F12 (&fonts::FreeSans12pt7b)
#define FB9 (&fonts::FreeSansBold9pt7b)
#define FB12 (&fonts::FreeSansBold12pt7b)
#define FB18 (&fonts::FreeSansBold18pt7b)
// portrait 320 x 480 (design "Portrait-*" on the claude.ai canvas). Rotation 0 or 2 (upside down), chosen on the
// Device tab and saved in flash ("rot"); the touch calibration does not depend on it
static uint8_t uiRot = 0;
static const int SW = 320, SH = 480;
static const int TOP_H = 30, NAV_H = 52, NAV_Y = SH - NAV_H;
enum { SCR_STATUS, SCR_FORECAST, SCR_WASH, SCR_DEVICE, SCR_WEB, SCR_N };
static const int TAB_W = SW / SCR_N;
static int scr = SCR_STATUS;
static bool confirmOpen = false, busy = false, lastRun = false;
static char washMsg[44] = "";
static uint32_t washMsgUntil = 0;

// ---------- text: smooth Inter fonts (fonts_inter.h, made by esp32/make_fonts.py) ----------
// The drawing code still names the old fonts (F9, FB12 ...) and a size factor; setF() picks the Inter font of the
// nearest real pixel size, so nothing is shrunk by fractions. Soft edges are blended with `surf`, the colour under
// the text (the panel cannot be read back), so whatever draws a card or button sets surf first.
static lgfx::VLWfont vR13, vR15, vR19, vB13, vB15, vB19, vB28;
static uint32_t surf;
static void fontsBegin() {
  struct { lgfx::VLWfont* f; const uint8_t* d; } all[] = {{&vR13, INTER_R13}, {&vR15, INTER_R15}, {&vR19, INTER_R19},
      {&vB13, INTER_B13}, {&vB15, INTER_B15}, {&vB19, INTER_B19}, {&vB28, INTER_B28}};
  for (auto& a : all) {
    auto* w = new lgfx::PointerWrapper();
    w->set(a.d);
    a.f->loadFont(w);
  }
}
static void setF(const lgfx::IFont* f, float sz = 1.0f) {
  bool bold = f == FB9 || f == FB12 || f == FB18;
  float px = (f == F12 || f == FB12 ? 19 : f == FB18 ? 28 : 15) * sz;
  const lgfx::IFont* r = bold ? (px >= 24 ? &vB28 : px >= 17 ? &vB19 : px >= 14 ? &vB15 : &vB13)
                              : (px >= 17 ? &vR19 : px >= 14 ? &vR15 : &vR13);
  tft.setFont(r);
  tft.setTextSize(1.0f);
}
static void txt(const char* s, int x, int y, const lgfx::IFont* f, uint32_t col, textdatum_t d = textdatum_t::middle_left, float sz = 1.0f) {
  setF(f, sz);
  tft.setBaseColor(surf);
  tft.setTextColor(col);
  tft.setTextDatum(d);
  tft.drawString(s, x, y);
}
// centered text wrapped by words inside maxW pixels; returns the next free y
static int wrapTxt(const char* s, int cx, int y, int maxW, uint32_t col, float sz = 0.85f, int step = 15) {
  char line[48] = "";
  const char* p = s;
  while (*p) {
    const char* e = strchr(p, ' ');
    int wl = e ? (int)(e - p) : (int)strlen(p);
    char t[48];
    snprintf(t, sizeof t, "%s%s%.*s", line, line[0] ? " " : "", wl, p);
    setF(F9, sz);
    int w = tft.textWidth(t);
    if (line[0] && w > maxW) {
      txt(line, cx, y, F9, col, textdatum_t::middle_center, sz);
      y += step;
      snprintf(line, sizeof line, "%.*s", wl, p);
    } else snprintf(line, sizeof line, "%s", t);
    p += wl + (e ? 1 : 0);
  }
  if (line[0]) { txt(line, cx, y, F9, col, textdatum_t::middle_center, sz); y += step; }
  return y;
}
// 12-hour clock: "4:41 PM" and "4 PM"
static void fmt12(char* o, size_t n, int h, int m) { snprintf(o, n, "%d:%02d %s", h % 12 ? h % 12 : 12, m, h < 12 ? "AM" : "PM"); }
static void fmtHour12(char* o, size_t n, int h) { snprintf(o, n, "%d %s", h % 12 ? h % 12 : 12, h < 12 ? "AM" : "PM"); }
static void card(int x, int y, int w, int h) {
  tft.fillSmoothRoundRect(x, y, w, h, 10, C_LINE);
  tft.fillSmoothRoundRect(x + 1, y + 1, w - 2, h - 2, 9, C_CARD);
  surf = C_CARD;  // text after a card is drawn on it
}
static void button(int x, int y, int w, int h, const char* s, bool primary, bool enabled = true, float sz = 1.0f) {
  uint32_t old = surf;
  if (primary) tft.fillSmoothRoundRect(x, y, w, h, 12, surf = enabled ? C_OK : C_TRACK);
  else {
    tft.fillSmoothRoundRect(x, y, w, h, 12, C_LINE);
    tft.fillSmoothRoundRect(x + 1, y + 1, w - 2, h - 2, 11, surf = C_BG);
  }
  txt(s, x + w / 2, y + h / 2, FB12, primary ? (enabled ? C_DARK : C_DIM) : C_FG, textdatum_t::middle_center, sz);
  surf = old;
}
static bool inRect(int px, int py, int x, int y, int w, int h) { return px >= x && px < x + w && py >= y && py < y + h; }

// local time (Baghdad = UTC+3) from the NTP clock
static bool localTm(struct tm& t) {
  time_t n = time(nullptr);
  if (n < 1700000000) return false;
  n += 3 * 3600;
  gmtime_r(&n, &t);
  return true;
}
static const char* MON[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
static const char* DOW[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};

static void fmtMMSS(char* o, size_t n, unsigned long leftMs) {
  unsigned long s = (leftMs + 999) / 1000;
  snprintf(o, n, "%02lu:%02lu", s / 60, s % 60);
}
static unsigned long runLeftMs() {
  unsigned long e = millis() - runStart;
  return e >= runMs ? 0 : runMs - e;
}
static int washesToday() {
  time_t n = time(nullptr);
  if (n < 1700000000) return 0;
  long today = (long)((n + 3 * 3600) / 86400);
  return prefs.getLong("day", -1) == today ? prefs.getInt("count", 0) : 0;
}

// English text for the decision reason
static void reasonText(char* o, size_t n) {
  const char* r = uc.reason;
  struct { const char* k; const char* t; } m[] = {
      {"raining", "Raining"}, {"dust storm", "Dust storm"}, {"model: next 6 h", "Rain/dust ahead"}, {"too hot", "Too hot"},
      {"no airport", "No airport data"}, {"device offline", "Device offline"}, {"waiting", "Settling after event"},
      {"daily cap", "Daily limit"}, {"min gap", "Daily limit"}, {"nothing to clean", "Panels clean"},
      {"after routine", "Routine wash"}, {"dust in air", "Dust in air"}};
  for (auto& e : m)
    if (strstr(r, e.k)) { snprintf(o, n, "%s", e.t); return; }
  snprintf(o, n, "%.22s", r);
}

// routine.due -> "due" / "today" / "24 Nov"
static const char* routineText(char* o, size_t n, uint32_t* col) {
  *col = C_FG;
  if (!uc.routineDue[0]) { snprintf(o, n, "-"); return o; }
  long long due = isoToEpoch(uc.routineDue);
  time_t now = time(nullptr);
  if (due < 0 || now < 1700000000) { snprintf(o, n, "-"); return o; }
  if ((long long)now >= due) { snprintf(o, n, "due"); *col = C_OK; return o; }
  time_t d = (time_t)due + 3 * 3600, t = now + 3 * 3600;
  if (d / 86400 == t / 86400) { snprintf(o, n, "today"); *col = C_OK; return o; }
  struct tm tm;
  gmtime_r(&d, &tm);
  snprintf(o, n, "%d %s", tm.tm_mday, MON[tm.tm_mon]);
  return o;
}

// ---------- top bar and navigation ----------
static void drawTop() {
  tft.fillRect(0, 0, SW, TOP_H - 1, surf = C_BG);
  tft.drawFastHLine(0, TOP_H - 1, SW, C_LINE);
  txt("HILLA PV", 12, 15, FB9, C_FG);
  char b[32];
  struct tm t;
  if (busy) txt("Updating...", 274, 15, F9, C_DUST, textdatum_t::middle_right);
  else {
    if (localTm(t)) {
      char tm12[12];
      fmt12(tm12, sizeof tm12, t.tm_hour, t.tm_min);
      snprintf(b, sizeof b, "%s %d %s %s", DOW[t.tm_wday], t.tm_mday, MON[t.tm_mon], tm12);
    } else snprintf(b, sizeof b, "--:--");
    txt(b, 274, 15, F9, C_DIM, textdatum_t::middle_right, 0.9f);
  }
  int lit = 0;
  if (WiFi.status() == WL_CONNECTED) {
    int r = WiFi.RSSI();
    lit = r > -60 ? 4 : r > -70 ? 3 : r > -80 ? 2 : 1;
  }
  for (int i = 0; i < 4; i++) {
    int h = 4 + i * 3;
    tft.fillRect(284 + i * 6, 22 - h, 4, h, i < lit ? C_OK : C_TRACK);
  }
}
static void drawNav() {
  static const char* names[] = {"Status", "Forecast", "Wash", "Device", "Web"};
  tft.fillRect(0, NAV_Y, SW, NAV_H, surf = C_NAV);
  tft.drawFastHLine(0, NAV_Y, SW, C_LINE);
  for (int i = 0; i < SCR_N; i++) {
    bool on = i == scr;
    if (on) tft.fillRect(i * TAB_W + TAB_W / 2 - 22, NAV_Y + 1, 44, 3, C_OK);
    txt(names[i], i * TAB_W + TAB_W / 2, NAV_Y + 27, on ? FB9 : F9, on ? C_OK : C_DIM, textdatum_t::middle_center, 0.8f);
  }
  surf = C_BG;
}

// ---------- Status screen ----------
static void arc(int cx, int cy, float p, uint32_t col) {  // progress ring starting at 12 o'clock
  const int r0 = 64, r1 = 76;
  if (p >= 0.999f) { tft.fillArc(cx, cy, r0, r1, 0, 360, col); return; }
  if (p <= 0) return;
  float a1 = 270 + 360 * p;
  if (a1 <= 360) tft.fillArc(cx, cy, r0, r1, 270, a1, col);
  else { tft.fillArc(cx, cy, r0, r1, 270, 360, col); tft.fillArc(cx, cy, r0, r1, 0, a1 - 360, col); }
}
static void drawRing() {
  const int cx = SW / 2, cy = 122;
  surf = C_BG;
  tft.fillRect(cx - 84, cy - 84, 168, 168, C_BG);
  tft.fillArc(cx, cy, 64, 76, 0, 360, C_TRACK);
  char big[16], sub[26], b[24];
  uint32_t col;
  float p = 1;
  if (running) {
    snprintf(big, sizeof big, "WASHING");
    col = C_OK;
    snprintf(sub, sizeof sub, "%s", "");
    p = runMs ? 1.0f - (float)runLeftMs() / runMs : 1;
  } else if (!uc.everOk) {
    snprintf(big, sizeof big, "NO DATA"); snprintf(sub, sizeof sub, "Waiting for server"); col = C_DIM;
  } else if (!strcmp(uc.action, "clean")) {
    snprintf(big, sizeof big, "CLEAN"); snprintf(sub, sizeof sub, "Wash requested"); col = C_OK;
  } else if (!strcmp(uc.action, "idle")) {
    snprintf(big, sizeof big, "IDLE"); reasonText(sub, sizeof sub); col = C_OK;
  } else {
    snprintf(big, sizeof big, "WAITING"); reasonText(sub, sizeof sub); col = C_DUST;
  }
  arc(cx, cy, p, col);
  if (running) {
    txt("WASHING", cx, cy - 18, FB12, col, textdatum_t::middle_center);
    fmtMMSS(b, sizeof b, runLeftMs());
    txt(b, cx, cy + 14, FB18, C_FG, textdatum_t::middle_center);
    return;
  }
  txt("AI decision", cx, cy - 36, F9, C_DIM, textdatum_t::middle_center, 0.8f);
  setF(FB18);
  txt(big, cx, cy - 6, tft.textWidth(big) <= 100 ? FB18 : FB12, col, textdatum_t::middle_center);
  // the sub line is up to 22 chars: shrink to two short lines when it does not fit the ring
  setF(F9, 0.8f);
  int sw = tft.textWidth(sub);
  if (sw <= 100) txt(sub, cx, cy + 28, F9, C_DIM, textdatum_t::middle_center, 0.8f);
  else {
    char* sp = strchr(sub + strlen(sub) / 2 - 3, ' ');
    if (!sp) { char cut[16]; snprintf(cut, sizeof cut, "%.12s", sub); txt(cut, cx, cy + 28, F9, C_DIM, textdatum_t::middle_center, 0.8f); }
    else {
      *sp = 0;
      txt(sub, cx, cy + 24, F9, C_DIM, textdatum_t::middle_center, 0.8f);
      txt(sp + 1, cx, cy + 40, F9, C_DIM, textdatum_t::middle_center, 0.8f);
    }
  }
}
static void gauge(int by, const char* name, float p, float th, uint32_t col) {
  char b[40];
  snprintf(b, sizeof b, "%s, next 6 h", name);
  txt(b, 24, by + 8, F9, C_DIM);
  if (p >= 0) snprintf(b, sizeof b, "%d%%", (int)(p * 100 + 0.5f)); else snprintf(b, sizeof b, "--");
  txt(b, 296, by + 8, FB12, col, textdatum_t::middle_right);
  const int bx = 24, bw = 272;
  tft.fillSmoothRoundRect(bx, by + 20, bw, 8, 4, C_TRACK);
  if (p >= 0) tft.fillSmoothRoundRect(bx, by + 20, max(8, (int)(p * bw)), 8, 4, col);
  if (th >= 0) {
    tft.fillRect(bx + (int)(th * bw), by + 17, 2, 14, C_FG);
    snprintf(b, sizeof b, "line = alarm level %d%%", (int)(th * 100 + 0.5f));
    txt(b, bx, by + 40, F9, C_DIM);
  }
}
static void chip(int x, const char* label, const char* val, uint32_t col) {
  card(x, 344, 92, 58);
  txt(label, x + 9, 359, F9, C_DIM, textdatum_t::middle_left, 0.85f);
  txt(val, x + 9, 384, FB12, col);
}
static void drawStatus() {
  drawRing();
  card(12, 210, 296, 122);
  gauge(218, "Rain", uc.everOk ? uc.pRain : -1, uc.thRain, C_RAIN);
  gauge(274, "Dust", uc.everOk ? uc.pDust : -1, uc.thDust, C_DUST);
  char b[24], c[24];
  uint32_t col;
  if (uc.pm10 >= 0) snprintf(b, sizeof b, "%d", (int)(uc.pm10 + 0.5f)); else snprintf(b, sizeof b, "--");
  chip(12, "PM10", b, C_FG);
  if (!isnan(fcTemp)) snprintf(b, sizeof b, "%d C", (int)lroundf(fcTemp)); else snprintf(b, sizeof b, "--");
  chip(114, "Temp", b, C_FG);
  routineText(c, sizeof c, &col);
  chip(216, "Routine", c, col);
  if (uc.pending[0]) {
    snprintf(b, sizeof b, "Pending: %.14s", uc.pending);
    surf = C_BG;
    txt(b, SW / 2, 414, F9, C_DIM, textdatum_t::middle_center, 0.85f);
  }
}

// ---------- Forecast screen ----------
static void drawForecast() {
  txt("NEXT 24 HOURS", 12, 46, F9, C_DIM, textdatum_t::middle_left, 0.85f);
  tft.fillSmoothCircle(212, 46, 4, C_RAIN);
  txt("rain", 220, 46, F9, C_FG, textdatum_t::middle_left, 0.85f);
  tft.fillSmoothCircle(262, 46, 4, C_DUST);
  txt("dust", 270, 46, F9, C_FG, textdatum_t::middle_left, 0.85f);
  if (!fcN) { txt("Forecast not loaded yet", SW / 2, 200, F12, C_DIM, textdatum_t::middle_center); return; }
  const int x0 = 16, bw = 12, H = 240, base = 64 + H;
  struct tm t;
  bool have = localTm(t);
  int cur = -1;
  for (int i = 0; i < fcN && have; i++) if (fch[i].day == t.tm_mday && fch[i].hour == t.tm_hour) cur = i;
  if (cur >= 0) tft.fillRect(x0 + cur * bw, 64, bw, H + 24, C_HI);
  tft.drawFastHLine(12, base, 296, C_LINE);
  for (int i = 0; i < fcN; i++) {
    int x = x0 + i * bw;
    int hr = max(2, min(H, (int)(fch[i].r * H + 0.5f))), hd = max(2, min(H, (int)(fch[i].d * H + 0.5f)));
    tft.fillRoundRect(x + 1, base - hr, 5, hr, hr >= 5 ? 2 : 0, C_RAIN);
    tft.fillRoundRect(x + 6, base - hd, 5, hd, hd >= 5 ? 2 : 0, C_DUST);
    if (i % 6 == 0) {
      char b[10];
      fmtHour12(b, sizeof b, fch[i].hour);
      txt(b, x, base + 13, F9, i == cur ? C_FG : C_DIM, textdatum_t::middle_left, 0.8f);
    }
  }
  if (uc.thRain >= 0) {
    int y = base - (int)(uc.thRain * H);
    for (int x = 12; x < 308; x += 8) tft.drawFastHLine(x, y, 4, C_RAIN);
  }
  char b[56] = "No rain above the alarm level in 24 h";
  for (int i = 0; i < fcN && uc.thRain >= 0; i++)
    if (fch[i].r >= uc.thRain) {
      char h[10];
      fmtHour12(h, sizeof h, fch[i].hour);
      snprintf(b, sizeof b, "Rain likely around %s%s", h, !have ? "" : fch[i].day == t.tm_mday ? " today" : " tomorrow");
      break;
    }
  card(12, 334, 296, 64);
  txt(b, 24, 356, FB9, C_FG, textdatum_t::middle_left, 0.9f);
  txt("No wash while a bar is above the line", 24, 380, F9, C_DIM, textdatum_t::middle_left, 0.8f);
}

// ---------- Wash screen ----------
static void lastWashText(char* o, size_t n) {
  // newest of: server's last_clean and the last run saved on this device (auto or manual)
  long long a = lastClean[0] ? isoToEpoch(lastClean) : -1, b = prefs.getLong64("last_run", 0);
  long long e = max(a, b);
  if (e < 1700000000) { snprintf(o, n, "-"); return; }
  time_t d = (time_t)e + 3 * 3600;
  struct tm tm;
  gmtime_r(&d, &tm);
  char h[12];
  fmt12(h, sizeof h, tm.tm_hour, tm.tm_min);
  snprintf(o, n, "%d %s %s", tm.tm_mday, MON[tm.tm_mon], h);
}
static void drawWashRight() {
  surf = C_BG;
  tft.fillRect(0, 188, SW, NAV_Y - 188, C_BG);
  char b[24];
  if (running) {
    card(12, 196, 296, 110);
    txt("Washing", SW / 2, 222, F12, C_OK, textdatum_t::middle_center);
    fmtMMSS(b, sizeof b, runLeftMs());
    txt(b, SW / 2, 264, FB18, C_FG, textdatum_t::middle_center);
  } else {
    button(12, 196, 296, 72, "Wash now", true);
    wrapTxt("Runs brush and pump for 1 minute. Daily limits still apply.", SW / 2, 290, 280, C_DIM);
  }
  surf = C_BG;
  if (washMsg[0]) wrapTxt(washMsg, SW / 2, 350, 280, C_BAD, 0.9f, 17);
}
static void drawConfirm() {
  card(24, 150, 272, 160);
  txt("Start a 1-minute wash?", SW / 2, 182, FB12, C_FG, textdatum_t::middle_center, 0.9f);
  char b[40];
  snprintf(b, sizeof b, "Counts as wash %d of %d today.", washesToday() + 1, MAX_PER_DAY);
  txt(b, SW / 2, 214, F9, C_DIM, textdatum_t::middle_center, 0.9f);
  button(40, 248, 114, 46, "Cancel", false);
  button(166, 248, 114, 46, "Start", true);
}
static void drawWash() {
  card(12, 42, 296, 136);
  char b[32], c[24];
  uint32_t col;
  lastWashText(b, sizeof b);
  struct { const char* l; const char* v; uint32_t c; } rows[3];
  rows[0] = {"Last wash", b, C_FG};
  rows[1] = {"Next routine", routineText(c, sizeof c, &col), col};
  char today[16];
  snprintf(today, sizeof today, "%d of %d", washesToday(), MAX_PER_DAY);
  rows[2] = {"Today", today, C_FG};
  for (int i = 0; i < 3; i++) {
    int y = 46 + i * 42;
    txt(rows[i].l, 26, y + 20, F9, C_DIM);
    txt(rows[i].v, 294, y + 20, FB9, rows[i].c, textdatum_t::middle_right);
    if (i < 2) tft.drawFastHLine(22, y + 41, 276, C_LINE);
  }
  drawWashRight();
  if (confirmOpen) drawConfirm();
}

// manual wash: same local limits as the server command, 1 minute, run by the panel controller;
// never touches last_id and sends no ack
static void startManualWash() {
  confirmOpen = false;
  washMsg[0] = 0;
  const char* why = washBlocked();
  char ans[40];
  if (why) snprintf(washMsg, sizeof washMsg, "%s", why);
  else if (!panelRun(60000UL, ans, sizeof ans)) snprintf(washMsg, sizeof washMsg, "%s", ans);
  else {
    countWash();
    Serial.println("MANUAL wash started on the panel for 1 min");
  }
  washMsgUntil = millis() + 6000;
}

// ---------- Device screen ----------
static void devRow(int i, const char* l, const char* v, uint32_t col, bool dot, uint32_t dotCol, bool labels) {
  int y = 44 + i * 40;
  if (labels) {
    txt(l, 26, y + 20, F9, C_DIM);
    if (i < 4) tft.drawFastHLine(22, y + 39, 276, C_LINE);
  } else tft.fillRect(120, y + 2, 182, 36, C_CARD);
  txt(v, 294, y + 20, F9, col, textdatum_t::middle_right);
  if (dot) {
    setF(F9);
    tft.fillSmoothCircle(294 - tft.textWidth(v) - 12, y + 20, 4, dotCol);
  }
}
static void drawDevRows(bool labels) {
  surf = C_CARD;
  char b[40];
  bool wf = WiFi.status() == WL_CONNECTED;
  String ssid = wf ? WiFi.SSID() : String("not connected");
  snprintf(b, sizeof b, "%.18s", ssid.c_str());
  devRow(0, "Wi-Fi", b, C_FG, false, 0, labels);
  if (wf) {
    int r = WiFi.RSSI();
    snprintf(b, sizeof b, "%d dBm - %s", r, r > -60 ? "good" : r > -75 ? "fair" : "weak");
  } else snprintf(b, sizeof b, "-");
  devRow(1, "Signal", b, C_FG, false, 0, labels);
  devRow(2, "Server", uc.ok ? "connected" : uc.everOk ? "no answer" : "not checked", C_FG, true, uc.ok ? C_OK : uc.everOk ? C_BAD : C_DIM, labels);
  if (!uc.everOk) snprintf(b, sizeof b, "never");
  else {
    unsigned long m = (millis() - uc.okMs) / 60000UL;
    if (m < 1) snprintf(b, sizeof b, "just now"); else snprintf(b, sizeof b, "%lu min ago", m);
  }
  devRow(3, "Last check", b, C_FG, false, 0, labels);
  devRow(4, "Panel", running ? "washing" : panelOnline ? "ready" : "offline", running ? C_OK : panelOnline ? C_FG : C_BAD,
         true, running ? C_OK : panelOnline ? C_OK : C_BAD, labels);
  unsigned long s = millis() / 1000UL;
  snprintf(b, sizeof b, "Up %lu d %lu h %lu min", s / 86400, (s / 3600) % 24, (s / 60) % 60);
  tft.fillRect(0, 398, SW, 24, surf = C_BG);
  txt(b, SW / 2, 410, F9, C_DIM, textdatum_t::middle_center, 0.85f);
}
// Device buttons, 2 x 2: Change Wi-Fi | Check now / Day-Night | Rotate
static const int BX[] = {12, 166, 12, 166}, BY[] = {256, 256, 322, 322}, BW = 142, BH = 56;
static void drawDevice() {
  card(12, 42, 296, 204);
  drawDevRows(true);
  const char* lab[] = {"Change Wi-Fi", "Check now", uiLight ? "Night mode" : "Day mode", "Rotate 180"};
  for (int i = 0; i < 4; i++) button(BX[i], BY[i], BW, BH, lab[i], false, true, 0.75f);
}

// ---------- Web screen: QR code of the live website (for the committee) ----------
static void drawWeb() {
  tft.fillSmoothRoundRect(50, 42, 220, 220, 12, TFT_WHITE);  // white card = the quiet zone around the code
  tft.qrcode("https://hilla-ai.duckdns.org/", 72, 64, 176, 2);
  txt("Live website", SW / 2, 282, FB12, C_FG, textdatum_t::middle_center);
  txt("Scan with a phone camera", SW / 2, 308, F9, C_DIM, textdatum_t::middle_center);
  txt("hilla-ai.duckdns.org", SW / 2, 332, FB9, C_OK, textdatum_t::middle_center);
  static const char* pts[] = {"AI rain & dust forecast", "Every hourly decision", "Washes and model results", "Arabic / English"};
  for (int i = 0; i < 4; i++) {
    tft.fillSmoothCircle(72, 358 + i * 17, 3, C_OK);
    txt(pts[i], 84, 358 + i * 17, F9, C_FG, textdatum_t::middle_left, 0.85f);
  }
}

// ---------- drawing control ----------
static void uiFull() {
  tft.fillRect(0, TOP_H, SW, NAV_Y - TOP_H, C_BG);
  drawTop();
  drawNav();  // leaves surf = C_BG for the page
  switch (scr) {
    case SCR_STATUS: drawStatus(); break;
    case SCR_FORECAST: drawForecast(); break;
    case SCR_WASH: drawWash(); break;
    case SCR_WEB: drawWeb(); break;
    default: drawDevice();
  }
}
static void uiPeriodic() {  // once a second: only the small parts that change
  drawTop();
  if (scr == SCR_STATUS && running) drawRing();
  else if (scr == SCR_WASH) {
    if (washMsg[0] && millis() > washMsgUntil) { washMsg[0] = 0; if (!confirmOpen) drawWashRight(); }
    else if (running && !confirmOpen) drawWashRight();
  } else if (scr == SCR_DEVICE) drawDevRows(false);
}
static void uiScreenMsg(const char* a, const char* b) {
  tft.fillScreen(surf = C_BG);
  txt("HILLA PV", SW / 2, 180, FB18, C_FG, textdatum_t::middle_center);
  wrapTxt(a, SW / 2, 236, 290, C_OK, 1.0f, 22);
  wrapTxt(b, SW / 2, 286, 290, C_DIM, 0.9f, 18);
}

// shown by wifiSetup(): connecting, or the setup network is open
void uiWifiScreen(bool force) {
  if (force) uiScreenMsg("Join Hilla-PV-Setup from your phone", "3 minutes. Then pick the new Wi-Fi network.");
  else uiScreenMsg("Connecting to Wi-Fi...", "If it fails: join Hilla-PV-Setup from your phone (3 min)");
}
void uiWifiDone() { uiFull(); }

// ---------- calibration (touch the arrows), saved as 8 numbers in flash ----------
static void uiCalibrate() {
  tft.fillScreen(surf = C_BG);
  txt("Touch the arrows to calibrate", SW / 2, SH / 2, F12, C_FG, textdatum_t::middle_center, 0.9f);
  uint16_t p[8];
  tft.calibrateTouch(p, (uint32_t)C_OK, (uint32_t)C_BG, 20);
  prefs.putBytes("calp", p, sizeof p);
  Serial.println("touch calibration saved");
}

void uiBegin() {
  applyTheme(prefs.getBool("light", false));
  uiRot = prefs.getUChar("rot", 0) == 2 ? 2 : 0;
  tft.init();
  fontsBegin();
  tft.setRotation(uiRot);  // portrait 320x480
  tft.fillScreen(C_BG);
  uiScreenMsg("Starting...", "Hold the screen now to recalibrate the touch");
  // hold a finger on the screen for the first 3 s -> calibrate again
  uint32_t t0 = millis();
  int n = 0, touched = 0;
  while (millis() - t0 < 3000) {
    if (millis() - t0 > 400) {
      int32_t x, y;
      n++;
      if (tft.getTouch(&x, &y)) touched++;
    }
    delay(20);
  }
  bool hold = n > 0 && touched * 10 >= n * 9;
  uint16_t p[8];
  if (!hold && prefs.getBytesLength("calp") == sizeof p) {
    prefs.getBytes("calp", p, sizeof p);
    tft.setTouchCalibrate(p);
  } else uiCalibrate();
  lastRun = running;
  uiFull();
}

// ---------- data from the server ----------
void uiPollResult(bool ok) {
  uc.ok = ok;
  if (ok) { uc.everOk = true; uc.okMs = millis(); }
}
void uiStoreCommand(JsonVariantConst d) {
  snprintf(uc.action, sizeof uc.action, "%s", d["action"] | "");
  snprintf(uc.reason, sizeof uc.reason, "%s", d["reason"] | "");
  uc.pRain = d["p_rain"] | -1.0f;
  uc.pDust = d["p_dust"] | -1.0f;
  uc.thRain = d["thresholds"]["rain"] | -1.0f;
  uc.thDust = d["thresholds"]["dust"] | -1.0f;
  uc.pm10 = d["now"]["pm10"] | -1.0f;
  snprintf(uc.routineDue, sizeof uc.routineDue, "%s", d["routine"]["due"] | "");
  uc.pending[0] = 0;
  for (JsonVariantConst v : d["pending"].as<JsonArrayConst>()) {
    if (uc.pending[0]) strlcat(uc.pending, "+", sizeof uc.pending);
    strlcat(uc.pending, v | "", sizeof uc.pending);
  }
  uiPollResult(true);
}

// extra request after a good poll: forecast bars, temperature, last clean. A failure here never matters for washing.
static void uiFetchStatus() {
  if (WiFi.status() != WL_CONNECTED) return;
  WiFiClientSecure tls;
  tls.setCACert(ROOT_CAS);
  HTTPClient http;
  http.setConnectTimeout(20000);
  http.setTimeout(20000);
  http.useHTTP10(true);  // no chunked answer, so it can be read as a stream
  if (!http.begin(tls, "https://hilla-ai.duckdns.org/api/status")) return;
  JsonDocument filter;
  filter["forecast"]["hours"][0]["time"] = true;
  filter["forecast"]["hours"][0]["p_rain"] = true;
  filter["forecast"]["hours"][0]["p_dust"] = true;
  filter["forecast"]["now"]["temp"] = true;
  filter["last_clean"] = true;
  JsonDocument doc;
  if (http.GET() == 200 && deserializeJson(doc, http.getStream(), DeserializationOption::Filter(filter)) == DeserializationError::Ok) {
    int n = 0;
    for (JsonObjectConst h : doc["forecast"]["hours"].as<JsonArrayConst>()) {
      const char* t = h["time"] | "";  // "2026-11-17T03:00" (Baghdad time)
      if (strlen(t) < 13 || n >= 24) continue;
      fch[n] = {(uint8_t)atoi(t + 11), (uint8_t)atoi(t + 8), h["p_rain"] | 0.0f, h["p_dust"] | 0.0f};
      n++;
    }
    if (n) fcN = n;
    if (!doc["forecast"]["now"]["temp"].isNull()) fcTemp = doc["forecast"]["now"]["temp"] | NAN;
    if (doc["last_clean"].is<const char*>()) snprintf(lastClean, sizeof lastClean, "%s", doc["last_clean"].as<const char*>());
  } else Serial.println("status request failed (ignored)");
  http.end();
}
void uiAfterPoll() {
  if (!uc.ok) return;
  if (running) uiStatusPending = true;  // do not hold the loop for ~20 s while the relays are on
  else uiFetchStatus();
}
void uiBusy(bool b) {
  busy = b;
  drawTop();
  if (!b) uiFull();
}

// ---------- touch ----------
static void onTap(int x, int y) {
  if (y >= NAV_Y) {
    int i = x / TAB_W;
    if (i > SCR_N - 1) i = SCR_N - 1;
    if (i != scr || confirmOpen) { scr = i; confirmOpen = false; uiFull(); }
    return;
  }
  if (scr == SCR_WASH) {
    if (confirmOpen) {
      if (inRect(x, y, 166, 248, 114, 46)) { startManualWash(); uiFull(); }
      else if (inRect(x, y, 40, 248, 114, 46)) { confirmOpen = false; uiFull(); }
    } else if (!running && inRect(x, y, 12, 196, 296, 72)) {
      washMsg[0] = 0;
      confirmOpen = true;
      drawConfirm();
    }
  } else if (scr == SCR_DEVICE) {
    if (inRect(x, y, BX[2], BY[2], BW, BH)) {  // day / night: allowed during a wash too
      applyTheme(!uiLight);
      prefs.putBool("light", uiLight);
      uiFull();
    } else if (inRect(x, y, BX[3], BY[3], BW, BH)) {  // turn the picture upside down
      uiRot = uiRot == 0 ? 2 : 0;
      prefs.putUChar("rot", uiRot);
      tft.setRotation(uiRot);
      uiFull();
    } else if (!running && inRect(x, y, BX[0], BY[0], BW, BH)) { wifiSetup(true); uiFull(); }
    else if (!running && inRect(x, y, BX[1], BY[1], BW, BH)) pollNow();
  }
}
void uiTick() {
  static uint32_t lastTouch = 0, lastSec = 0;
  static bool was = false;
  uint32_t ms = millis();
  if (ms - lastTouch >= 20) {
    lastTouch = ms;
    int32_t x, y;
    bool t = tft.getTouch(&x, &y);
    if (t && !was) onTap(x, y);
    was = t;
  }
  if (running != lastRun) {  // a wash started or ended: redraw the whole screen
    lastRun = running;
    confirmOpen = false;
    uiFull();
    lastSec = ms;
  } else if (ms - lastSec >= 1000) {
    lastSec = ms;
    uiPeriodic();
  }
  if (!running && uiStatusPending) {
    uiStatusPending = false;
    uiFetchStatus();
    uiFull();
  }
}
