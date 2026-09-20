# 📡 Panduan Integrasi Hardware IoT (ESP32 & ESP32-CAM)

Sistem ini menggunakan arsitektur **Asinkron & Real-Time Telemetry** sehingga ESP32 tidak akan freeze/ngelag saat jepret kamera atau baca sensor loadcell.

---

## 🏗️ Alur Kerja Sistem (Workflow)

```
[ ESP32 Timbangan ] --(Tiap 200ms Live Stream)--> POST /api/v1/telemetry/live   --> [ Layar Live Gauge Dashboard ]
[ ESP32 Timbangan ] --(Saat Bobot Stabil/Tombol)--> POST /api/v1/measurements     --> [ Tersimpan ke Database SQLite ]
[ ESP32-CAM Foto ]  --(Jepret Kapan Saja Asinkron)-> POST /api/v1/photos/upload   --> [ Auto-Link ke Data Timbangan ]
```

---

## 1. Live Telemetry Stream (High-Frequency Real-Time)

Gunakan ini di `loop()` ESP32 untuk mengirimkan fluktuasi angka timbangan secara live ke web dashboard tanpa bikin database jebol.

* **Endpoint:** `POST http://<IP_SERVER>:8080/api/v1/telemetry/live`
* **Header:** `Content-Type: application/json`
* **Payload:**
```json
{
  "device_id": "ESP32-SCALE-01",
  "weight_grams": 3450.5,
  "length_cm": 50.2,
  "is_stable": false
}
```

### 💻 Contoh Snippet Arduino (ESP32):
```cpp
void sendLiveTelemetry(float weight, float length, bool isStable) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin("http://192.168.1.50:8080/api/v1/telemetry/live");
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<200> doc;
    doc["device_id"] = "ESP32-SCALE-01";
    doc["weight_grams"] = weight;
    doc["length_cm"] = length;
    doc["is_stable"] = isStable;

    String body;
    serializeJson(doc, body);
    http.POST(body);
    http.end();
  }
}
```

---

## 2. Commit Hasil Timbangan (Simpan Permanen ke Database)

Kirim ini saat **bobot bayi sudah stabil** atau **tombol "Simpan"** di alat ditekan.

* **Endpoint:** `POST http://<IP_SERVER>:8080/api/v1/measurements`
* **Header:** `Content-Type: application/json`
* **Payload:**
```json
{
  "device_id": "ESP32-SCALE-01",
  "weight_grams": 3520.0,
  "length_cm": 50.8,
  "notes": "Bayi Ny. Siti - Posyandu Melati"
}
```

---

## 3. Upload Foto Kamera Asinkron (ESP32-CAM)

ESP32-CAM cukup jepret foto dan kirim ke endpoint ini. Server akan **otomatis me-link foto ini ke data timbangan terakhir**.

* **Endpoint:** `POST http://<IP_SERVER>:8080/api/v1/photos/upload`
* **Header:** `Content-Type: multipart/form-data`
* **Fields:**
  - `device_id` (Text): `ESP32-CAM-01`
  - `photo` (File): Image JPEG binary

### 💻 Contoh Snippet ESP32-CAM:
```cpp
void uploadPhotoAsync() {
  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Gagal ambil foto kamera");
    return;
  }

  WiFiClient client;
  HTTPClient http;
  String boundary = "----ESP32Boundary7MA4YWxkTrZu0gW";

  http.begin(client, "http://192.168.1.50:8080/api/v1/photos/upload");
  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);

  String head = "--" + boundary + "\r\n";
  head += "Content-Disposition: form-data; name=\"device_id\"\r\n\r\nESP32-CAM-01\r\n";
  head += "--" + boundary + "\r\n";
  head += "Content-Disposition: form-data; name=\"photo\"; filename=\"baby.jpg\"\r\n";
  head += "Content-Type: image/jpeg\r\n\r\n";

  String tail = "\r\n--" + boundary + "--\r\n";

  size_t totalLen = head.length() + fb->len + tail.length();
  uint8_t *payload = (uint8_t*) malloc(totalLen);
  if (payload) {
    memcpy(payload, head.c_str(), head.length());
    memcpy(payload + head.length(), fb->buf, fb->len);
    memcpy(payload + head.length() + fb->len, tail.c_str(), tail.length());

    int httpCode = http.sendRequest("POST", payload, totalLen);
    Serial.printf("Foto uploaded! Status: %d\n", httpCode);
    free(payload);
  }

  esp_camera_fb_return(fb);
  http.end();
}
```
