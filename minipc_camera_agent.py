#!/usr/bin/env python3
"""
Saestu IoT - Mini PC Logitech Webcam & Telemetry Agent
Script ini dijalankan di Mini PC (Linux/Ubuntu/Raspberry Pi/Windows).
Tugas:
1. Menangkap gambar dari Logitech USB Webcam (dengan auto-exposure warmup).
2. Mengirimkan foto via HTTP POST multipart ke Go Web Service.
3. (Opsional) Menjembatani data Serial dari Arduino/ESP32 ke Web Service.
"""

import sys
import time
import argparse
import io

import sys
import time
import argparse
import io

def check_dependencies():
    missing = []
    try:
        import cv2
    except ImportError:
        missing.append("opencv-python")
    try:
        import requests
    except ImportError:
        missing.append("requests")
    
    if missing:
        print(f"[ERROR] Dependensi belum lengkap: {', '.join(missing)}")
        print(f"        Jalankan perintah ini di Mini PC: pip install {' '.join(missing)}")
        sys.exit(1)


def capture_logitech_frame(camera_index=0, warmup_frames=10, width=1280, height=720):
    """
    Menangkap 1 frame bersih dari kamera Logitech.
    Warmup frames sangat penting agar auto-exposure & white balance Logitech tidak gelap/buram.
    """
    print(f"[*] Membuka kamera Logitech di index /dev/video{camera_index}...")
    cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        print(f"[ERROR] Tidak dapat mengakses kamera index {camera_index}. Pastikan kabel USB Logitech terpasang.")
        return None

    # Set resolusi (Logitech C270/C920/dll support 720p/1080p)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    # Warm-up auto exposure
    print("[*] Menstabilkan auto-exposure & fokus Logitech...")
    frame = None
    for _ in range(warmup_frames):
        ret, temp_frame = cap.read()
        if ret:
            frame = temp_frame
        time.sleep(0.05)

    cap.release()

    if frame is None:
        print("[ERROR] Gagal membaca frame dari webcam Logitech.")
        return None

    # Encode ke JPEG di memory (tanpa perlu write ke disk mini PC)
    success, encoded_image = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not success:
        print("[ERROR] Gagal mengompres frame ke JPEG.")
        return None

    return encoded_image.tobytes()


def upload_photo(server_url, image_bytes, device_id="MINIPC-LOGITECH-01", measurement_id=None):
    """
    Mengirimkan byte image ke Go Web Service endpoint /api/v1/photos/upload
    """
    endpoint = f"{server_url.rstrip('/')}/api/v1/photos/upload"
    print(f"[*] Mengunggah foto ke Web Service: {endpoint}...")

    files = {
        'photo': ('baby_capture.jpg', io.BytesIO(image_bytes), 'image/jpeg')
    }
    data = {
        'device_id': device_id
    }
    if measurement_id:
        data['measurement_id'] = str(measurement_id)

    try:
        response = requests.post(endpoint, data=data, files=files, timeout=10)
        if response.status_code == 200:
            result = response.json()
            print(f"[SUCCESS] Foto berhasil diunggah!")
            print(f"          Photo URL      : {result.get('photo_url')}")
            print(f"          Measurement ID : #{result.get('measurement_id')}")
            return True
        else:
            print(f"[FAILED] Server mengembalikan HTTP {response.status_code}: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Gagal koneksi ke server: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Saestu Mini PC Logitech Capture Agent")
    parser.add_argument("--server", default="http://localhost:8080", help="URL Go Server (misal: http://192.168.1.50:8080)")
    parser.add_argument("--device", default="MINIPC-LOGITECH-01", help="Device ID Mini PC")
    parser.add_argument("--camera", type=int, default=0, help="Index kamera USB (default: 0)")
    parser.add_argument("--measurement-id", type=int, default=None, help="Opsional: ID timbangan spesifik untuk di-link")
    parser.add_argument("--loop", type=int, default=0, help="Jika diisi > 0, akan jepret otomatis tiap N detik")

    args = parser.parse_args()
    check_dependencies()

    print("==================================================")
    print("🚀 Saestu Mini PC Logitech Agent")
    print(f"🎯 Target Server : {args.server}")
    print(f"📷 Camera Index  : {args.camera}")
    print(f"🏷️ Device ID     : {args.device}")
    print("==================================================")

    if args.loop > 0:
        print(f"[*] Menjalankan mode loop tiap {args.loop} detik. Tekan Ctrl+C untuk berhenti.")
        try:
            while True:
                img_data = capture_logitech_frame(camera_index=args.camera)
                if img_data:
                    upload_photo(args.server, img_data, device_id=args.device, measurement_id=args.measurement_id)
                time.sleep(args.loop)
        except KeyboardInterrupt:
            print("\n[*] Dihentikan oleh user.")
    else:
        # One-shot snap
        img_data = capture_logitech_frame(camera_index=args.camera)
        if img_data:
            upload_photo(args.server, img_data, device_id=args.device, measurement_id=args.measurement_id)


if __name__ == "__main__":
    main()
