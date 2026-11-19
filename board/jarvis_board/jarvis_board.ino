// Jarvis 2.0 — ears for the Waveshare ESP32-S3-LCD-1.85 (non-touch, screen not used)
//
// Hold the BOOT button, talk, let go. The board records with its onboard mic and
// sends the audio to the Jarvis server on the Umbrel Pi, which answers on the Nest Mini.
//
// Arduino IDE settings (Tools menu):
//   Board: "ESP32S3 Dev Module"   (esp32 by Espressif >= 3.0)
//   PSRAM: "OPI PSRAM"            Flash size: 16MB
//   USB CDC On Boot: "Enabled"    (so Serial Monitor works over USB-C)

#include <WiFi.h>
#include <HTTPClient.h>
#include <ESP_I2S.h>
#include "secrets.h"

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

I2SClass mic;
uint8_t *wavBuf = nullptr;
const size_t HEADER = 44;
const size_t MAX_PCM = (size_t)SAMPLE_RATE * 2 * MAX_SECONDS;

static void put32(uint8_t *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }
static void put16(uint8_t *p, uint16_t v) { p[0] = v; p[1] = v >> 8; }

void writeWavHeader(uint8_t *h, uint32_t pcmBytes) {
  memcpy(h, "RIFF", 4);      put32(h + 4, 36 + pcmBytes);
  memcpy(h + 8, "WAVEfmt ", 8);
  put32(h + 16, 16);          put16(h + 20, 1);            // PCM
  put16(h + 22, 1);           put32(h + 24, SAMPLE_RATE);  // mono, 16 kHz
  put32(h + 28, SAMPLE_RATE * 2); put16(h + 32, 2); put16(h + 34, 16);
  memcpy(h + 36, "data", 4);  put32(h + 40, pcmBytes);
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Wi-Fi: connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(250); Serial.print("."); }
  Serial.println(WiFi.status() == WL_CONNECTED ? " ok, IP " + WiFi.localIP().toString() : " failed");
}

void flushMic() {
  // throw away ~60 ms of old audio sitting in the I2S buffers
  static char junk[512];
  for (int i = 0; i < 4; i++) mic.readBytes(junk, sizeof(junk));
}

size_t record() {
  flushMic();
  uint8_t *pcm = wavBuf + HEADER;
  size_t got = 0;
  Serial.println("Listening... (let go of BOOT when done)");
  while (digitalRead(BOOT_BTN) == LOW && got < MAX_PCM) {
    size_t want = min((size_t)1024, MAX_PCM - got);
    size_t n = mic.readBytes((char *)(pcm + got), want);
    // boost volume with clipping
    int16_t *s = (int16_t *)(pcm + got);
    for (size_t i = 0; i < n / 2; i++) {
      int32_t v = (int32_t)s[i] * MIC_GAIN;
      s[i] = v > 32767 ? 32767 : (v < -32768 ? -32768 : v);
    }
    got += n;
  }
  while (digitalRead(BOOT_BTN) == LOW) delay(10);  // max length reached: wait for release
  return got;
}

void sendToJarvis(size_t pcmBytes) {
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) return;
  writeWavHeader(wavBuf, pcmBytes);

  HTTPClient http;
  http.begin(String(JARVIS_URL) + "/api/talk");
  http.addHeader("Content-Type", "audio/wav");
  http.addHeader("X-Jarvis-Key", JARVIS_KEY);
  http.setTimeout(30000);
  Serial.printf("Sending %.1f s to Jarvis...\n", pcmBytes / (SAMPLE_RATE * 2.0));
  int code = http.POST(wavBuf, HEADER + pcmBytes);
  Serial.printf("Jarvis answered (%d): %s\n", code, http.getString().c_str());
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nJarvis 2.0 board starting");
  pinMode(BOOT_BTN, INPUT_PULLUP);

  wavBuf = (uint8_t *)ps_malloc(HEADER + MAX_PCM);
  if (!wavBuf) { Serial.println("No PSRAM! Set Tools > PSRAM to OPI PSRAM."); while (true) delay(1000); }

  mic.setPins(MIC_BCLK, MIC_WS, -1, MIC_DIN);
  if (!mic.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_RIGHT)) {
    Serial.println("Microphone failed to start");
    while (true) delay(1000);
  }
  connectWiFi();
  Serial.println("Ready: hold BOOT and talk.");
}

void loop() {
  if (digitalRead(BOOT_BTN) == LOW) {
    delay(30);  // debounce
    if (digitalRead(BOOT_BTN) == LOW) {
      size_t bytes = record();
      if (bytes >= (size_t)SAMPLE_RATE * 2 * MIN_MS / 1000) sendToJarvis(bytes);
      else Serial.println("Too short, ignored.");
    }
  }
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  delay(10);
}
