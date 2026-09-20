#!/usr/bin/env python3
"""
Saestu IoT Full End-to-End Simulation Script
-------------------------------------------
Simulates:
1. ESP32 Loadcell & Ultrasonic/Laser Sensor (Live SSE Telemetry every 200ms)
2. Stabilization cycle (Menimbang -> Stabil)
3. DB Measurement Commit (POST /api/v1/measurements)
4. Mini PC + Logitech Webcam Async Photo Generation & Upload (POST /api/v1/photos/upload)
"""

import time
import math
import random
import io
import json
import urllib.request
import urllib.parse
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

API_BASE = "http://localhost:8080"
DEVICE_ID = "SIM-SCALE-BAYI-01"

NAMES = [
    "Bayi Ny. Siti Aminah",
    "Bayi Ny. Dewi Lestari",
    "Bayi Ny. Rina Marlina",
    "Bayi Ny. Fitriani",
    "Bayi Ny. Sri Wahyuni"
]

def generate_mock_baby_photo(baby_name, weight_kg, length_cm):
    """Generates an in-memory realistic JPEG mock photo if PIL is installed, else mock JPEG bytes"""
    if not HAS_PIL:
        # Fallback minimal 1x1 valid JPEG
        return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'

    # Create 640x480 realistic baby scale photo with ruler overlay
    img = Image.new('RGB', (640, 480), color='#1e293b')
    draw = ImageDraw.Draw(img)

    # Background Mat
    draw.rectangle([(40, 40), (600, 440)], fill='#334155', outline='#64748b', width=2)
    # Scale tray area
    draw.rounded_rectangle([(80, 80), (560, 400)], radius=20, fill='#f1f5f9')

    # Baby silhouette / placeholder ellipse
    draw.ellipse([(200, 160), (440, 320)], fill='#fecdd3', outline='#fda4af', width=3)
    draw.ellipse([(170, 200), (240, 280)], fill='#fecdd3') # head

    # Ruler marks on mat
    for x in range(100, 550, 20):
        h = 15 if (x - 100) % 100 == 0 else 8
        draw.line([(x, 380), (x, 380 - h)], fill='#0f172a', width=2)

    # Info banner overlay (OSD)
    draw.rectangle([(0, 0), (640, 35)], fill='#09090b')
    text_info = f"LOGITECH C920 HD PRO | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {DEVICE_ID}"
    draw.text((15, 10), text_info, fill='#10b981')

    # Measurement details OSD
    draw.rectangle([(50, 410), (590, 435)], fill='#0f172a')
    osd_metrics = f"{baby_name}  |  BB: {weight_kg:.2f} kg  |  TB: {length_cm:.1f} cm"
    draw.text((65, 415), osd_metrics, fill='#f8fafc')

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return buf.getvalue()

def post_json(endpoint, data):
    url = f"{API_BASE}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read().decode('utf-8'))

def upload_photo(image_bytes, filename="simulated_capture.jpg", length_cm=None):
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode('utf-8'))
    body.extend(f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode('utf-8'))
    body.extend(b"Content-Type: image/jpeg\r\n\r\n")
    body.extend(image_bytes)
    body.extend(f"\r\n--{boundary}\r\n".encode('utf-8'))
    body.extend(f'Content-Disposition: form-data; name="device_id"\r\n\r\n{DEVICE_ID}\r\n'.encode('utf-8'))
    if length_cm and length_cm > 0:
        body.extend(f"--{boundary}\r\n".encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="length_cm"\r\n\r\n{length_cm}\r\n'.encode('utf-8'))
    body.extend(f"--{boundary}--\r\n".encode('utf-8'))

    req = urllib.request.Request(
        f"{API_BASE}/api/v1/photos/upload",
        data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode('utf-8'))

def simulate_one_session(session_num=1):
    baby_name = random.choice(NAMES)
    target_weight = random.uniform(3100.0, 4200.0) # grams (3.1 - 4.2 kg)
    target_length = random.uniform(48.0, 53.5)     # cm

    # Simulasi kasus: jika session_num genap, hardware sensor TB null/0 -> dihitung via MediaPipe dari gambar
    is_tb_sensor_null = (session_num % 2 == 0)

    print(f"\n=======================================================")
    print(f"[*] SESI PENIMBANGAN #{session_num}: {baby_name}")
    print(f"[*] Target Berat: {target_weight/1000:.2f} kg ({target_weight:.0f} g)")
    if is_tb_sensor_null:
        print(f"[*] Skenario: Sensor Fisik TB NULL/0 -> Akan dihitung via MediaPipe Pose dari foto!")
    else:
        print(f"[*] Skenario: Sensor Fisik TB Terpasang ({target_length:.1f} cm)")
    print(f"=======================================================")

    # Phase 1: Baby placed on scale -> Fluctuations (Menimbang)
    steps = 15 # 15 * 0.2s = 3 seconds of settling
    current_val = 0.0

    print("[ESP32] Bayi ditaruh di loadcell, sensor berfluktuasi...")
    for i in range(steps):
        noise = random.uniform(-150.0, 150.0)
        progress = (i + 1) / steps
        current_val = (target_weight * progress) + noise
        current_len = 0.0 if is_tb_sensor_null else (target_length + random.uniform(-1.5, 1.5))

        post_json("/api/v1/telemetry/live", {
            "device_id": DEVICE_ID,
            "weight_grams": max(0.0, round(current_val, 1)),
            "length_cm": round(current_len, 1),
            "is_stable": False
        })
        time.sleep(0.2)

    # Phase 2: Weight stabilized (Stabil)
    print("[ESP32] Pembacaan stabil tercapai (is_stable = true)!")
    stable_weight = target_weight + random.uniform(-5.0, 5.0)
    stable_length = 0.0 if is_tb_sensor_null else target_length

    for _ in range(5):
        post_json("/api/v1/telemetry/live", {
            "device_id": DEVICE_ID,
            "weight_grams": round(stable_weight, 1),
            "length_cm": round(stable_length, 1),
            "is_stable": True
        })
        time.sleep(0.2)

    # Phase 3: ESP32 commits record (Jika sensor TB null, kirim length_cm = 0)
    print(f"[ESP32] Menyimpan data penimbangan awal ke SQLite DB (TB: {stable_length:.1f} cm)...")
    commit_res = post_json("/api/v1/measurements", {
        "device_id": DEVICE_ID,
        "weight_grams": round(stable_weight, 1),
        "length_cm": round(stable_length, 1),
        "notes": baby_name
    })
    record_id = commit_res.get("data", {}).get("id") or commit_res.get("id")
    print(f"[SUCCESS] Record awal tersimpan ID #{record_id}")

    # Phase 4: Mini PC captures webcam photo, detects Pose via MediaPipe, & uploads
    print("[Mini PC Logitech] Shutter trigger -> Mengambil snapshot HD...")
    photo_bytes = generate_mock_baby_photo(baby_name, stable_weight/1000.0, target_length)

    mediapipe_length = None
    if is_tb_sensor_null:
        # Simulasi deteksi landmark pose (crown -> shoulder -> hip -> knee -> ankle)
        mediapipe_length = round(target_length + random.uniform(-0.3, 0.3), 1)
        print(f"[Mini PC MediaPipe] Sensor TB kosong! Pose Landmark terdeteksi: 520px -> Estimasi TB: {mediapipe_length} cm")

    print("[Mini PC Logitech] Mengunggah foto kamera + estimasi TB ke server...")
    upload_res = upload_photo(
        photo_bytes, 
        f"capture_{int(time.time())}.jpg", 
        length_cm=mediapipe_length
    )
    photo_url = upload_res.get("photo_url", "")
    print(f"[Mini PC Logitech] Foto terunggah: {photo_url}")
    print(f"[UI UPDATE] Cek dashboard: data #{record_id} foto & TB ({upload_res.get('length_cm', stable_length)} cm) otomatis sinkron via SSE!")

def main():
    print("==================================================")
    print("    SAESTU IOT END-TO-END SIMULATION RUNNER       ")
    print("==================================================")
    print(f"Target Server: {API_BASE}")
    print("Simulasi akan menjalankan live telemetry stream,")
    print("kalkulasi stabilitas loadcell, auto-capture webcam mock,")
    print("serta auto-commit data ke database.")
    print("Tekan Ctrl+C untuk berhenti.\n")

    session = 1
    try:
        while True:
            simulate_one_session(session)
            session += 1
            print("\nMenunggu 6 detik sebelum sesi penimbangan berikutnya...")
            time.sleep(6)
    except KeyboardInterrupt:
        print("\n[Simulasi Dihentikan].")

if __name__ == "__main__":
    main()
