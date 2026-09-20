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


def estimate_height_mediapipe(cv2_frame, pixels_per_cm=10.0):
    """
    Menghitung estimasi panjang/tinggi badan menggunakan MediaPipe Pose Landmarks.
    Jarak dihitung dari:
    - Crown / Hidung / Telinga (Head) -> Bahu (Shoulder) -> Pinggul (Hip) -> Lutut (Knee) -> Tumit (Ankle/Heel).
    pixels_per_cm: Faktor kalibrasi kamera (default 10 px/cm, sesuaikan dengan jarak fixture kamera ke matras).
    """
    try:
        import mediapipe as mp
        import numpy as np
    except ImportError:
        print("[INFO] mediapipe belum terinstall di Mini PC. Gunakan: pip install mediapipe")
        return None

    mp_pose = mp.solutions.pose
    with mp_pose.Pose(static_image_mode=True, model_complexity=1, min_detection_confidence=0.5) as pose:
        rgb_frame = cv2.cvtColor(cv2_frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb_frame)

        if not results.pose_landmarks:
            print("[MediaPipe] Landmark tubuh tidak terdeteksi pada gambar.")
            return None

        h, w, _ = cv2_frame.shape
        lm = results.pose_landmarks.landmark

        # Helper untuk koordinat piksel
        def get_pt(idx):
            return np.array([lm[idx].x * w, lm[idx].y * h])

        # 1. Head midpoint (Nose or Mid-eyes)
        nose = get_pt(mp_pose.PoseLandmark.NOSE)
        
        # 2. Mid Shoulder
        l_sh = get_pt(mp_pose.PoseLandmark.LEFT_SHOULDER)
        r_sh = get_pt(mp_pose.PoseLandmark.RIGHT_SHOULDER)
        mid_sh = (l_sh + r_sh) / 2.0

        # 3. Mid Hip
        l_hip = get_pt(mp_pose.PoseLandmark.LEFT_HIP)
        r_hip = get_pt(mp_pose.PoseLandmark.RIGHT_HIP)
        mid_hip = (l_hip + r_hip) / 2.0

        # 4. Leg segment (Knee & Ankle, ambil sisi dengan confidence tertinggi)
        l_vis = (lm[mp_pose.PoseLandmark.LEFT_KNEE].visibility + lm[mp_pose.PoseLandmark.LEFT_ANKLE].visibility) / 2.0
        r_vis = (lm[mp_pose.PoseLandmark.RIGHT_KNEE].visibility + lm[mp_pose.PoseLandmark.RIGHT_ANKLE].visibility) / 2.0

        if l_vis >= r_vis:
            knee = get_pt(mp_pose.PoseLandmark.LEFT_KNEE)
            ankle = get_pt(mp_pose.PoseLandmark.LEFT_ANKLE)
            heel = get_pt(mp_pose.PoseLandmark.LEFT_HEEL) if hasattr(mp_pose.PoseLandmark, 'LEFT_HEEL') else ankle
        else:
            knee = get_pt(mp_pose.PoseLandmark.RIGHT_KNEE)
            ankle = get_pt(mp_pose.PoseLandmark.RIGHT_ANKLE)
            heel = get_pt(mp_pose.PoseLandmark.RIGHT_HEEL) if hasattr(mp_pose.PoseLandmark, 'RIGHT_HEEL') else ankle

        # Multi-segment Body Length (Head-to-Shoulder + Torso + Thigh + LowerLeg)
        seg1 = np.linalg.norm(nose - mid_sh) * 1.25 # Estimasi ubun-ubun (crown) dari hidung
        seg2 = np.linalg.norm(mid_sh - mid_hip)      # Torso
        seg3 = np.linalg.norm(mid_hip - knee)       # Paha
        seg4 = np.linalg.norm(knee - heel)          # Betis & Tumit

        total_pixels = seg1 + seg2 + seg3 + seg4
        estimated_cm = round(total_pixels / pixels_per_cm, 1)

        print(f"[MediaPipe] Pose terdeteksi! Total piksel: {total_pixels:.1f}px -> Estimasi TB: {estimated_cm} cm")
        return estimated_cm


def capture_logitech_frame(camera_index=0, warmup_frames=10, width=1280, height=720):
    """
    Menangkap 1 frame bersih dari kamera Logitech.
    Warmup frames sangat penting agar auto-exposure & white balance Logitech tidak gelap/buram.
    """
    print(f"[*] Membuka kamera Logitech di index /dev/video{camera_index}...")
    cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        print(f"[ERROR] Tidak dapat mengakses kamera index {camera_index}. Pastikan kabel USB Logitech terpasang.")
        return None, None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

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
        return None, None

    success, encoded_image = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not success:
        print("[ERROR] Gagal mengompres frame ke JPEG.")
        return None, None

    return frame, encoded_image.tobytes()


def upload_photo(server_url, image_bytes, device_id="MINIPC-LOGITECH-01", measurement_id=None, length_cm=None):
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
    if length_cm and length_cm > 0:
        data['length_cm'] = str(length_cm)

    try:
        response = requests.post(endpoint, data=data, files=files, timeout=10)
        if response.status_code == 200:
            result = response.json()
            print(f"[SUCCESS] Foto berhasil diunggah!")
            print(f"          Photo URL      : {result.get('photo_url')}")
            print(f"          Measurement ID : #{result.get('measurement_id')}")
            if length_cm:
                print(f"          Estimated TB   : {length_cm} cm (MediaPipe Pose)")
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
    parser.add_argument("--mediapipe", action="store_true", default=True, help="Aktifkan estimasi tinggi badan via MediaPipe Pose (default: True)")
    parser.add_argument("--px-per-cm", type=float, default=10.0, help="Faktor kalibrasi kamera (piksel per cm, default: 10.0)")
    parser.add_argument("--loop", type=int, default=0, help="Jika diisi > 0, akan jepret otomatis tiap N detik")

    args = parser.parse_args()
    check_dependencies()

    print("==================================================")
    print("🚀 Saestu Mini PC Logitech Agent")
    print(f"🎯 Target Server : {args.server}")
    print(f"📷 Camera Index  : {args.camera}")
    print(f"🏷️ Device ID     : {args.device}")
    print(f"📐 MediaPipe TB  : {'Aktif (' + str(args.px_per_cm) + ' px/cm)' if args.mediapipe else 'Nonaktif'}")
    print("==================================================")

    def process_and_upload():
        raw_frame, img_bytes = capture_logitech_frame(camera_index=args.camera)
        if not img_bytes:
            return
        
        est_tb = None
        if args.mediapipe and raw_frame is not None:
            est_tb = estimate_height_mediapipe(raw_frame, pixels_per_cm=args.px_per_cm)

        upload_photo(
            args.server, 
            img_bytes, 
            device_id=args.device, 
            measurement_id=args.measurement_id,
            length_cm=est_tb
        )

    if args.loop > 0:
        print(f"[*] Menjalankan mode loop tiap {args.loop} detik. Tekan Ctrl+C untuk berhenti.")
        try:
            while True:
                process_and_upload()
                time.sleep(args.loop)
        except KeyboardInterrupt:
            print("\n[*] Dihentikan oleh user.")
    else:
        process_and_upload()


if __name__ == "__main__":
    main()
