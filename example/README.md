# Sample Test Images for Saestu Computer Vision Measurement

Folder ini berisi 3 gambar uji coba yang telah dikalibrasi presisi dengan parameter default sistem Saestu.

## Daftar Gambar Uji Coba:

### 1. `1_mediapipe_infant.jpg`
- **Metode Cocok:** `MediaPipe Pose (AI Keypoint)`
- **Kalibrasi Default:** Skala Frame Matras (`maxDimCm = 100 cm`)
- **Deskripsi:** Foto klinis bayi usia 6 bulan di atas matras pemeriksaan Posyandu dengan orientasi kepala hingga tumit terlihat jelas.
- **Hasil Estimasi:** ~51.9 cm (Confidence > 0.99)

### 2. `2_contour_silhouette.jpg`
- **Metode Cocok:** `Siluet Kontur (Bebas Landmark)`
- **Kalibrasi Default:** Skala Frame Matras (`maxDimCm = 100 cm`)
- **Deskripsi:** Siluet morfologi tubuh bayi dengan kontras matras medis yang bersih.
- **Hasil Estimasi:** ~65.2 cm (Caliper ujung kepala ke tumit)

### 3. `3_aruco_optical_metrology.jpg`
- **Metode Cocok:** `ArUco Metrologi (Marker Fisik)`
- **Kalibrasi Default:** Ukuran Marker Fisik (`markerSizeCm = 10.0 cm`, Dictionary `DICT_4X4_50`, Marker ID 0)
- **Deskripsi:** Matras bayi dilengkapi dengan fiducial marker ArUco 4x4 (10x10 cm) di pojok atas untuk kalibrasi pixel-per-metric (PPM) otomatis tanpa bergantung pada jarak kamera.
- **Hasil Estimasi:** ~65.7 cm (Marker ID: 0 terdeteksi, confidence 0.97)
