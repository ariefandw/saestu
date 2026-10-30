# Dataset Gambar Uji Coba Pengukuran Panjang Badan Saestu (Ground Truth TB)

Ketiga gambar di bawah ini adalah foto dokumenter klinis otentik (real photorealistic) posisi telentang (*supine*) yang sudah dikalibrasi presisi dengan parameter default sistem Saestu. Nilai Ground Truth Tinggi Badan (TB) dicantumkan langsung di nama file untuk memudahkan verifikasi dan pengujian otomatis.

---

## 1. `1_mediapipe_tb61.3cm_kalibrasi100cm.jpg`
- **Metode Pengujian:** `MediaPipe Pose (AI Keypoint)`
- **Ground Truth TB:** **`61.3 cm`**
- **Kalibrasi Default:** Skala Frame Bidang Matras = `100.0 cm` (`maxDimCm = 100`)
- **Deskripsi Klinis:** Bayi usia 5 bulan berbaring telentang di atas *infantometer* Posyandu resmi dengan mistar ukur cm tertera di samping tubuh.
- **Deteksi Algoritma:** BlazePose mendeteksi 33 landmark anatomi:
  - Ubun-ubun (*Crown*) ke bahu: 106.8 px
  - Bahu ke panggul (*Mid-Hip*): 277.3 px
  - Panggul ke tumit (*Leg Length*): 351.0 px
  - **Confidence:** `0.993` (99.3%)

---

## 2. `2_contour_tb78.6cm_kalibrasi100cm.jpg`
- **Metode Pengujian:** `Siluet Kontur (Bebas Landmark)`
- **Ground Truth TB:** **`78.6 cm`**
- **Kalibrasi Default:** Skala Frame Bidang Matras = `100.0 cm` (`maxDimCm = 100`)
- **Deskripsi Klinis:** Bayi usia 6 bulan di atas matras vinil pediatrik biru polos tanpa penghalang.
- **Deteksi Algoritma:** Segmentasi morfologi *bounding caliper box* dari ujung ubun-ubun kepala hingga ujung tumit kaki dengan kontras warna latar matras yang bersih.
  - **Confidence:** `0.88`

---

## 3. `3_aruco_tb79.3cm_marker10cm.jpg`
- **Metode Pengujian:** `ArUco Metrologi (Marker Fisik)`
- **Ground Truth TB:** **`79.3 cm`**
- **Kalibrasi Default:** Ukuran Fisik Marker = `10.0 cm` (`markerSizeCm = 10.0`, Dictionary `DICT_4X4_50`, ID: 0)
- **Deskripsi Klinis:** Foto bayi di atas matras pemeriksaan dilengkapi kartu kalibrasi fiducial ArUco 4x4 (10x10 cm) di pojok atas matras.
- **Deteksi Algoritma:** Deteksi otomatis *fiducial marker* fisik untuk kalibrasi piksel per sentimeter (*PPM = 11.9 px/cm*) tanpa bergantung pada jarak atau zoom kamera.
  - **Marker ID Terdeteksi:** `0` (Sisi marker: `119 px` = `10.0 cm`)
  - **Confidence:** `0.97` (97%)
