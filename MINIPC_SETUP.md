# 🖥️ Panduan Setup Mini PC + Webcam Logitech

Panduan ini khusus untuk tim hardware/mahasiswa yang memegang **Mini PC** dengan kamera **Logitech USB**.

---

## 1. Persiapan di Mini PC

Mini PC (baik memakai OS Ubuntu, Raspberry Pi OS, Debian, atau Windows) hanya butuh Python 3 dan 2 library:

```bash
# Masuk ke terminal Mini PC
pip install opencv-python requests
```

*(Catatan jika memakai Raspberry Pi OS / Linux minimal, install juga dependency v4l2 jika diperlukan: `sudo apt-get install -y libv4l-dev python3-opencv`)*

---

## 2. Cara Menjalankan Script Capture

File script: [`minipc_camera_agent.py`](file:///C:/dev/saestu/minipc_camera_agent.py)

### A. Jepret Sekali (One-Shot) saat Penimbangan Selesai
```bash
python minipc_camera_agent.py --server http://192.168.1.50:8080 --device MINIPC-POSYANDU-01
```
*Ganti `192.168.1.50` dengan alamat IP komputer server tempat Go backend berjalan.*

### B. Menentukan Index Kamera (Jika ada lebih dari 1 kamera USB)
```bash
python minipc_camera_agent.py --server http://192.168.1.50:8080 --camera 1
```

### C. Mode Loop Berkala (Otomatis Jepret tiap 5 Detik)
```bash
python minipc_camera_agent.py --server http://192.168.1.50:8080 --loop 5
```

---

## 3. Integrasi Trigger Tombol Fisik di Mini PC (Opsional)

Jika tim mahasiswa memiliki tombol fisik (misal push button di GPIO Mini PC):

```python
# trigger_button.py
import RPi.GPIO as GPIO # atau library GPIO mini PC terkait
import subprocess

BUTTON_PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Siap menerima penimbangan...")
while True:
    if GPIO.input(BUTTON_PIN) == GPIO.LOW:
        print("Tombol timbang ditekan! Menjepret kamera...")
        subprocess.run(["python3", "minipc_camera_agent.py", "--server", "http://192.168.1.50:8080"])
```
