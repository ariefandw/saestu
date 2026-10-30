# Dataset Foto Uji Coba Pengukuran Panjang Badan Saestu (Cross-Method Benchmark)

Folder ini berisi **3 foto mentahan klinis (raw documentary photos)** untuk **3 bayi yang berbeda**. **Setiap gambar dapat diuji ke SEMUA metode Computer Vision** (MediaPipe Pose, Siluet Kontur, dan ArUco Metrologi) dengan parameter kalibrasi default (`maxDimCm = 100 cm`, `markerSizeCm = 10.0 cm`).

Nama file murni mencantumkan identitas subjek dan **TB Actual (Ground Truth)** hasil ukur fisik:

---

## 1. `bayi1_tb61.3cm.jpg`
- **Subjek:** Bayi 1 (Usia 5 bulan, rambut hitam, onesie putih).
- **TB Actual (Ground Truth):** **`61.3 cm`** (Terverifikasi mistar ukur infantometer fisik di samping bayi).
- **Karakteristik:** Berbaring di atas matras infantometer Posyandu.
- **Hasil Uji Komparasi 3 Metode:**
  - **MediaPipe Pose:** `61.1 cm` (Confidence 99.3%, deviasi: -0.2 cm)
  - **Siluet Kontur:** `81.0 cm` (Caliper bounding box termasuk matras)
  - **ArUco Metrologi:** `85.1 cm`

---

## 2. `bayi2_tb78.6cm.jpg`
- **Subjek:** Bayi 2 (Usia 6 bulan, rambut cokelat terang, onesie putih).
- **TB Actual (Ground Truth):** **`78.6 cm`** (Orientasi kepala ke tumit).
- **Karakteristik:** Berbaring di atas matras vinil pediatrik biru polos dengan kartu ArUco di pojok atas.
- **Hasil Uji Komparasi 3 Metode:**
  - **MediaPipe Pose:** `59.5 cm` (Confidence 99.6%)
  - **Siluet Kontur:** `78.6 cm` (Confidence 88%, deviasi: 0.0 cm)
  - **ArUco Metrologi:** `79.3 cm` (Confidence 97%, deviasi: +0.7 cm)

---

## 3. `bayi3_tb80.7cm.jpg`
- **Subjek:** Bayi 3 (Usia 4 bulan, rambut lebat, romper *coral-red* cerah).
- **TB Actual (Ground Truth):** **`80.7 cm`**.
- **Karakteristik:** Berbaring di atas matras klinis dengan kartu kalibrasi fiducial ArUco 4x4 (10x10 cm).
- **Hasil Uji Komparasi 3 Metode:**
  - **MediaPipe Pose:** `58.8 cm` (Confidence 99.2%)
  - **Siluet Kontur:** `60.9 cm` (Confidence 88%)
  - **ArUco Metrologi:** `80.7 cm` (Confidence 97%, deviasi: 0.0 cm)
