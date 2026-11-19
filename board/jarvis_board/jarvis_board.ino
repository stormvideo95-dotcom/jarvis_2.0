// Jarvis 2.0 — ears for the Waveshare ESP32-S3-LCD-1.85 (non-touch, screen not used)
//
// Hold BOOT, talk, let go. The board records with its onboard mic and sends the
// audio to the Jarvis server on the Umbrel Pi, which answers on the Nest Mini.
//
// First start (or Wi-Fi not reachable, or BOOT held 10 s): the board opens a Wi-Fi
// hotspot "Jarvis-Setup". Join it with your phone, a setup page opens, fill in
// Wi-Fi + Pi address + Jarvis key. Saved on the board, no reflashing needed.
//
// Ready-made firmware: flash from https://stormvideo95-dotcom.github.io/jarvis_2.0/
// Build yourself (Arduino IDE): ESP32S3 Dev Module, OPI PSRAM, 16MB, USB CDC On Boot Enabled.

#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <ESP_I2S.h>

#define FW_VERSION "1.1"

// ---- Board pins (ESP32-S3-LCD-1.85 onboard microphone) ----
#define MIC_BCLK   15
#define MIC_WS      2
#define MIC_DIN    39
#define BOOT_BTN    0     // BOOT button, LOW when pressed

// ---- Recording ----
#define SAMPLE_RATE   16000
#define MAX_SECONDS   8
#define MIC_GAIN      4      // the onboard mic is quiet; raise to 6-8 if Jarvis mishears you
#define MIN_MS        300    // shorter presses are ignored
#define SETUP_HOLD_MS 10000  // hold BOOT this long to open the setup hotspot

I2SClass mic;
Preferences prefs;
uint8_t *wavBuf = nullptr;
const size_t HEADER = 44;
const size_t MAX_PCM = (size_t)SAMPLE_RATE * 2 * MAX_SECONDS;

String cfgSsid, cfgPass, cfgUrl, cfgKey;

// ============================================================ settings
void loadSettings() {
  prefs.begin("jarvis", true);
  cfgSsid = prefs.getString("ssid", "");
  cfgPass = prefs.getString("pass", "");
  cfgUrl  = prefs.getString("url", "");
  cfgKey  = prefs.getString("key", "");
  prefs.end();
}

void saveSettings(const String &s, const String &p, const String &u, const String &k) {
  prefs.begin("jarvis", false);
  prefs.putString("ssid", s);
  prefs.putString("pass", p);
  prefs.putString("url", u);
  prefs.putString("key", k);
  prefs.end();
}

// ============================================================ setup hotspot
String htmlEscape(const String &in) {
  String o;
  for (char c : in) {
    if (c == '&') o += "&amp;"; else if (c == '<') o += "&lt;";
    else if (c == '>') o += "&gt;"; else if (c == '"') o += "&quot;"; else o += c;
  }
  return o;
}

String setupPage(const String &options) {
  String url = cfgUrl.length() ? cfgUrl : "http://192.168.1.10:8790";
  String h = F("<!doctype html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'><title>Jarvis setup</title>"
    "<style>body{margin:0;font-family:system-ui,sans-serif;background:#0b0d12;color:#e8ebf2}"
    "main{max-width:420px;margin:0 auto;padding:28px 18px}.orb{width:56px;height:56px;border-radius:50%;"
    "border:3px solid #ffb020;display:grid;place-items:center;margin-bottom:12px}.orb i{width:22px;height:22px;"
    "border-radius:50%;background:#ffb020}h1{font-size:24px;margin:0 0 4px}p{color:#8b93a7;margin:0 0 20px}"
    "label{display:block;font-size:13px;color:#8b93a7;margin:14px 0 6px}input,select{width:100%;box-sizing:border-box;"
    "background:#151924;border:1px solid #262c3b;color:#e8ebf2;border-radius:12px;padding:12px;font-size:16px}"
    "button{margin-top:22px;width:100%;background:#ffb020;color:#1b1200;border:0;border-radius:12px;padding:14px;"
    "font-size:16px;font-weight:600}small{color:#8b93a7}</style></head><body><main>"
    "<div class='orb'><i></i></div><h1>Jarvis setup</h1><p>Fill this in once. The board remembers it.</p>"
    "<form method='POST' action='/save'>"
    "<label>Wi-Fi (2.4 GHz)</label><select name='ssid_pick' onchange=\"document.getElementById('s').value=this.value\">"
    "<option value=''>Pick your Wi-Fi...</option>");
  h += options;
  h += F("</select><label>...or type the name</label><input id='s' name='ssid' value='");
  h += htmlEscape(cfgSsid);
  h += F("' required><label>Wi-Fi password</label><input name='pass' type='password'>"
         "<label>Jarvis on the Pi</label><input name='url' value='");
  h += htmlEscape(url);
  h += F("' required><label>Jarvis key</label><input name='key' value='");
  h += htmlEscape(cfgKey);
  h += F("' required><small>The Pi install shows the address and key at the end.</small>"
         "<button>Save and connect</button></form></main></body></html>");
  return h;
}

void runSetupPortal() {
  Serial.println("Setup mode: join Wi-Fi 'Jarvis-Setup' with your phone");
  WiFi.disconnect(true);
  WiFi.mode(WIFI_AP_STA);
  int n = WiFi.scanNetworks();
  String options;
  for (int i = 0; i < n; i++) {
    String s = WiFi.SSID(i);
    if (s.length() == 0 || options.indexOf("value=\"" + htmlEscape(s) + "\"") >= 0) continue;
    options += "<option value=\"" + htmlEscape(s) + "\">" + htmlEscape(s) + "</option>";
  }
  WiFi.softAP("Jarvis-Setup");
  delay(200);
  IPAddress ip = WiFi.softAPIP();

  DNSServer dns;
  dns.start(53, "*", ip);  // every address points to us -> phone shows the setup page
  WebServer server(80);
  bool saved = false;

  server.on("/save", HTTP_POST, [&]() {
    String s = server.arg("ssid"); s.trim();
    String u = server.arg("url");  u.trim();
    while (u.endsWith("/")) u.remove(u.length() - 1);
    if (!u.startsWith("http")) u = "http://" + u;
    String k = server.arg("key");  k.trim();
    saveSettings(s, server.arg("pass"), u, k);
    server.send(200, "text/html",
      "<meta name='viewport' content='width=device-width,initial-scale=1'>"
      "<body style='font-family:system-ui;background:#0b0d12;color:#e8ebf2;padding:30px'>"
      "<h2>Saved!</h2><p>Jarvis restarts and joins " + htmlEscape(s) + ". You can close this page.</p></body>");
    saved = true;
  });
  server.onNotFound([&]() { server.send(200, "text/html", setupPage(options)); });
  server.begin();

  unsigned long started = millis();
  while (!saved) {
    dns.processNextRequest();
    server.handleClient();
    delay(2);
    if (millis() - started > 15UL * 60 * 1000) break;  // 15 min idle: retry Wi-Fi
  }
  delay(1500);
  ESP.restart();
}

// ============================================================ Wi-Fi + audio
bool connectWiFi(uint32_t timeoutMs) {
  if (WiFi.status() == WL_CONNECTED) return true;
  if (cfgSsid.isEmpty()) return false;
  Serial.printf("Wi-Fi: connecting to %s", cfgSsid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(cfgSsid.c_str(), cfgPass.c_str());
  uint32_t t = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t < timeoutMs) { delay(250); Serial.print("."); }
  bool ok = WiFi.status() == WL_CONNECTED;
  Serial.println(ok ? " ok, IP " + WiFi.localIP().toString() : " failed");
  return ok;
}

static void put32(uint8_t *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }
static void put16(uint8_t *p, uint16_t v) { p[0] = v; p[1] = v >> 8; }

void writeWavHeader(uint8_t *h, uint32_t pcmBytes) {
  memcpy(h, "RIFF", 4);      put32(h + 4, 36 + pcmBytes);
  memcpy(h + 8, "WAVEfmt ", 8);
  put32(h + 16, 16);          put16(h + 20, 1);
  put16(h + 22, 1);           put32(h + 24, SAMPLE_RATE);
  put32(h + 28, SAMPLE_RATE * 2); put16(h + 32, 2); put16(h + 34, 16);
  memcpy(h + 36, "data", 4);  put32(h + 40, pcmBytes);
}

void flushMic() {
  static char junk[512];
  for (int i = 0; i < 4; i++) mic.readBytes(junk, sizeof(junk));
}

// returns bytes recorded; sets wantSetup if BOOT was held for SETUP_HOLD_MS
size_t record(bool &wantSetup) {
  flushMic();
  uint8_t *pcm = wavBuf + HEADER;
  size_t got = 0;
  uint32_t start = millis();
  Serial.println("Listening... (let go of BOOT when done)");
  while (digitalRead(BOOT_BTN) == LOW && got < MAX_PCM) {
    size_t want = min((size_t)1024, MAX_PCM - got);
    size_t n = mic.readBytes((char *)(pcm + got), want);
    int16_t *s = (int16_t *)(pcm + got);
    for (size_t i = 0; i < n / 2; i++) {
      int32_t v = (int32_t)s[i] * MIC_GAIN;
      s[i] = v > 32767 ? 32767 : (v < -32768 ? -32768 : v);
    }
    got += n;
  }
  while (digitalRead(BOOT_BTN) == LOW) {
    if (millis() - start > SETUP_HOLD_MS) { wantSetup = true; break; }
    delay(10);
  }
  return got;
}

void sendToJarvis(size_t pcmBytes) {
  if (!connectWiFi(15000)) return;
  writeWavHeader(wavBuf, pcmBytes);
  HTTPClient http;
  http.begin(cfgUrl + "/api/talk");
  http.addHeader("Content-Type", "audio/wav");
  http.addHeader("X-Jarvis-Key", cfgKey);
  http.setTimeout(30000);
  Serial.printf("Sending %.1f s to Jarvis...\n", pcmBytes / (SAMPLE_RATE * 2.0));
  int code = http.POST(wavBuf, HEADER + pcmBytes);
  Serial.printf("Jarvis answered (%d): %s\n", code, http.getString().c_str());
  http.end();
}

// ============================================================ main
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nJarvis 2.0 board v" FW_VERSION);
  pinMode(BOOT_BTN, INPUT_PULLUP);
  loadSettings();

  if (cfgSsid.isEmpty() || cfgUrl.isEmpty() || !connectWiFi(30000)) runSetupPortal();

  wavBuf = (uint8_t *)ps_malloc(HEADER + MAX_PCM);
  if (!wavBuf) { Serial.println("No PSRAM found!"); while (true) delay(1000); }

  mic.setPins(MIC_BCLK, MIC_WS, -1, MIC_DIN);
  if (!mic.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_RIGHT)) {
    Serial.println("Microphone failed to start");
    while (true) delay(1000);
  }
  Serial.println("Ready: hold BOOT and talk. (Hold BOOT 10 s for setup.)");
}

void loop() {
  if (digitalRead(BOOT_BTN) == LOW) {
    delay(30);
    if (digitalRead(BOOT_BTN) == LOW) {
      bool wantSetup = false;
      size_t bytes = record(wantSetup);
      if (wantSetup) runSetupPortal();
      if (bytes >= (size_t)SAMPLE_RATE * 2 * MIN_MS / 1000) sendToJarvis(bytes);
      else Serial.println("Too short, ignored.");
    }
  }
  static uint32_t lastTry = 0;
  if (WiFi.status() != WL_CONNECTED && millis() - lastTry > 10000) {
    lastTry = millis();
    connectWiFi(8000);
  }
  delay(10);
}
