# Dataset Foto Uji Coba Pengukuran Panjang Badan Saestu (Ground Truth TB)

Folder ini berisi **3 foto mentahan (raw clinical photos)** untuk **3 bayi yang berbeda** dalam posisi telentang (*supine*) dengan parameter **kalibrasi default** (`maxDimCm = 100 cm`, `markerSizeCm = 10.0 cm`). Nilai **TB Actual (Ground Truth)** dicantumkan langsung di nama file untuk memudahkan verifikasi dan benchmarking.

---

## 1. `bayi1_mediapipe_tb_actual_61.3cm.jpg`
- **Subjek:** Bayi 1 (Usia 5 bulan, rambut hitam, baju putih).
- **Model Uji:** **MediaPipe Pose** (AI Keypoint 33-Landmark BlazePose).
- **TB Actual:** **`61.3 cm`**
- **Kalibrasi:** Skala Frame Bidang Matras = `100.0 cm` (Default).
- **Setting Klinis:** Bayi berbaring di atas *infantometer* Posyandu dengan mistar ukur cm fisik di samping tubuh.
- **Hasil Deteksi:**
  - Ubun-ubun (*Crown*) ke bahu: 106.8 px
  - Bahu ke panggul (*Mid-Hip*): 277.3 px
  - Panggul ke tumit (*Leg Length*): 351.0 px
  - **Confidence:** `0.993` (99.3%)

---

## 2. `bayi2_contour_tb_actual_78.6cm.jpg`
- **Subjek:** Bayi 2 (Usia 6 bulan, rambut cokelat terang, baju putih).
- **Model Uji:** **Siluet Kontur** (Bebas Landmark & Morfologi Caliper).
- **TB Actual:** **`78.6 cm`**
- **Kalibrasi:** Skala Frame Bidang Matras = `100.0 cm` (Default).
- **Setting Klinis:** Bayi berbaring di atas matras vinil pediatrik biru polos tanpa distraksi.
- **Hasil Deteksi:**
  - Segmentasi kontur siluet tubuh dari ubun-ubun kepala hingga ujung tumit kaki dengan *minimum bounding box caliper*.
  - **Confidence:** `0.88` (88%)

---

## 3. `bayi3_aruco_tb_actual_80.7cm.jpg`
- **Subjek:** Bayi 3 (Usia 4 bulan, rambut lebat, romper *coral-red* cerah).
- **Model Uji:** **ArUco Metrologi** (Kalibrasi Marker Fisik).
- **TB Actual:** **`80.7 cm`**
- **Kalibrasi:** Ukuran Fisik Marker = `10.0 cm` (Default, Dictionary `DICT_4X4_50`, Marker ID: 0).
- **Setting Klinis:** Bayi berbaring di atas matras pemeriksaan dengan kartu kalibrasi fiducial ArUco 4x4 (10x10 cm) di pojok atas matras.
- **Hasil Deteksi:**
  - Marker ID #0 terdeteksi otomatis, menghasilkan kalibrasi metrologi `11.9 px/cm`.
  - Tubuh tersegmentasi otomatis dan diukur sepanjang aksis kepala-tumit.
  - **Confidence:** `0.97` (97%)
