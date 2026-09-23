import os
import cv2
import numpy as np
import base64
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

app = Flask(__name__)
CORS(app)

MODEL_PATH = "pose_landmarker.task"
base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
options = vision.PoseLandmarkerOptions(
    base_options=base_options,
    output_segmentation_masks=False
)
detector = vision.PoseLandmarker.create_from_options(options)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Baby Height Estimator - MediaPipe</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: #0b0f19;
            color: #f3f4f6;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 2rem 1rem;
        }
        .container {
            max-width: 1000px;
            width: 100%;
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 1.25rem;
            padding: 2rem;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
        }
        header {
            margin-bottom: 2rem;
            border-bottom: 1px solid #1f2937;
            padding-bottom: 1.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        h1 {
            font-size: 1.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .badge {
            background: rgba(56, 189, 248, 0.1);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.3);
            padding: 0.35rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
        }
        .card {
            background: #161f30;
            border: 1px solid #233148;
            border-radius: 1rem;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }
        .control-group label {
            display: block;
            font-size: 0.85rem;
            font-weight: 600;
            color: #9ca3af;
            margin-bottom: 0.5rem;
        }
        input[type="number"], select {
            width: 100%;
            padding: 0.75rem 1rem;
            background: #0b0f19;
            border: 1px solid #374151;
            border-radius: 0.5rem;
            color: #fff;
            font-size: 0.95rem;
            outline: none;
        }
        input[type="number"]:focus {
            border-color: #38bdf8;
        }
        .dropzone {
            border: 2px dashed #374151;
            border-radius: 0.75rem;
            padding: 2rem 1rem;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s ease;
            background: #0f172a;
        }
        .dropzone:hover {
            border-color: #38bdf8;
            background: #131d33;
        }
        .btn {
            background: linear-gradient(135deg, #0284c7, #6366f1);
            color: white;
            border: none;
            padding: 0.85rem 1.5rem;
            border-radius: 0.5rem;
            font-weight: 700;
            cursor: pointer;
            width: 100%;
            transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.9; }
        .btn-test {
            background: #1f2937;
            border: 1px solid #374151;
            color: #d1d5db;
            margin-top: 0.5rem;
        }
        .btn-test:hover { background: #374151; }
        .preview-box {
            position: relative;
            background: #0b0f19;
            border-radius: 0.75rem;
            border: 1px solid #233148;
            overflow: hidden;
            min-height: 360px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .preview-box img {
            max-width: 100%;
            height: auto;
            display: block;
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }
        .metric-box {
            background: #0b0f19;
            border: 1px solid #233148;
            border-radius: 0.75rem;
            padding: 1rem;
            text-align: center;
        }
        .metric-label {
            font-size: 0.75rem;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .metric-val {
            font-size: 1.5rem;
            font-weight: 800;
            color: #10b981;
            margin-top: 0.25rem;
        }
        .metric-val.secondary {
            color: #38bdf8;
        }
        .loading-spinner {
            display: none;
            border: 4px solid rgba(255, 255, 255, 0.1);
            border-left-color: #38bdf8;
            border-radius: 50%;
            width: 36px;
            height: 36px;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>Baby Height Estimator</h1>
                <p style="color: #9ca3af; font-size: 0.85rem; margin-top: 0.25rem;">Powered by Google MediaPipe Pose Landmarker</p>
            </div>
            <div class="badge">Scale: 1m max dimension</div>
        </header>

        <div class="grid">
            <div class="card">
                <h3 style="font-size: 1.1rem;">Input Settings</h3>
                <div class="control-group">
                    <label>Real-World Scale (Max Dimension in Meters)</label>
                    <input type="number" id="scaleInput" value="1.0" step="0.05" min="0.1">
                </div>

                <div class="dropzone" id="dropzone" onclick="document.getElementById('fileInput').click()">
                    <input type="file" id="fileInput" accept="image/*" style="display: none">
                    <div style="font-size: 2rem; margin-bottom: 0.5rem;">📸</div>
                    <div style="font-weight: 600; font-size: 0.95rem;">Click or Drag Photo Here</div>
                    <div style="font-size: 0.8rem; color: #9ca3af; margin-top: 0.25rem;" id="fileName">Supports JPG, PNG, WebP</div>
                </div>

                <button class="btn" id="analyzeBtn" onclick="analyzeUploadedImage()">Hitung Tinggi Badan</button>
                <button class="btn btn-test" onclick="loadSampleTest()">🧪 Gunakan Sample Gambar Bayi</button>
            </div>

            <div class="card">
                <h3 style="font-size: 1.1rem;">Hasil Deteksi & Pengukuran</h3>
                <div class="metrics-grid">
                    <div class="metric-box">
                        <div class="metric-label">Tinggi Segmented (Skeleton)</div>
                        <div class="metric-val" id="segmentedHeight">-- cm</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Garis Lurus (Euclidean)</div>
                        <div class="metric-val secondary" id="straightHeight">-- cm</div>
                    </div>
                </div>

                <div class="preview-box" id="previewBox">
                    <div class="loading-spinner" id="spinner"></div>
                    <span id="emptyPlaceholder" style="color: #6b7280; font-size: 0.9rem;">Belum ada gambar yang diproses</span>
                    <img id="resultImage" style="display: none;" alt="Result visualization">
                </div>
            </div>
        </div>
    </div>

    <script>
        const fileInput = document.getElementById('fileInput');
        const fileName = document.getElementById('fileName');
        const spinner = document.getElementById('spinner');
        const emptyPlaceholder = document.getElementById('emptyPlaceholder');
        const resultImage = document.getElementById('resultImage');
        const segmentedHeight = document.getElementById('segmentedHeight');
        const straightHeight = document.getElementById('straightHeight');
        let currentBase64 = null;

        fileInput.addEventListener('change', function(e) {
            if (e.target.files.length > 0) {
                const file = e.target.files[0];
                fileName.innerText = file.name;
                const reader = new FileReader();
                reader.onload = function(evt) {
                    currentBase64 = evt.target.result;
                };
                reader.readAsDataURL(file);
            }
        });

        async function analyzeUploadedImage() {
            if (!currentBase64) {
                alert('Pilih gambar terlebih dahulu atau klik "Gunakan Sample Gambar Bayi"');
                return;
            }
            runInference(currentBase64);
        }

        async function loadSampleTest() {
            spinner.style.display = 'block';
            emptyPlaceholder.style.display = 'none';
            resultImage.style.display = 'none';

            try {
                const res = await fetch('/api/sample');
                const data = await res.json();
                currentBase64 = 'data:image/jpeg;base64,' + data.base64;
                fileName.innerText = "sample_baby.jpg";
                runInference(currentBase64);
            } catch(e) {
                alert('Gagal memuat sample: ' + e);
                spinner.style.display = 'none';
            }
        }

        async function runInference(b64) {
            spinner.style.display = 'block';
            emptyPlaceholder.style.display = 'none';
            resultImage.style.display = 'none';

            const scale = parseFloat(document.getElementById('scaleInput').value) || 1.0;

            try {
                const res = await fetch('/api/detect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: b64, scale_meters: scale })
                });

                const data = await res.json();
                spinner.style.display = 'none';

                if (data.success) {
                    resultImage.src = 'data:image/jpeg;base64,' + data.annotated_image;
                    resultImage.style.display = 'block';
                    segmentedHeight.innerText = data.segmented_height_cm.toFixed(2) + ' cm';
                    straightHeight.innerText = data.straight_height_cm.toFixed(2) + ' cm';
                } else {
                    emptyPlaceholder.style.display = 'block';
                    emptyPlaceholder.innerText = 'Pose tidak terdeteksi: ' + (data.error || 'Pastikan seluruh tubuh bayi terlihat');
                }
            } catch (err) {
                spinner.style.display = 'none';
                emptyPlaceholder.style.display = 'block';
                emptyPlaceholder.innerText = 'Error: ' + err;
            }
        }
    </script>
</body>
</html>
"""

def process_pose(img_bgr, real_world_max_dimension_meters=1.0):
    h, w, _ = img_bgr.shape
    max_dim_px = max(h, w)
    meters_per_pixel = real_world_max_dimension_meters / max_dim_px
    cm_per_pixel = meters_per_pixel * 100.0

    # Convert BGR to RGB for MP
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
    detection_result = detector.detect(mp_image)

    if not detection_result.pose_landmarks:
        return None

    landmarks = detection_result.pose_landmarks[0]

    def pt(idx):
        lm = landmarks[idx]
        return np.array([lm.x * w, lm.y * h])

    nose = pt(0)
    left_ear = pt(7)
    right_ear = pt(8)
    mid_ear = (left_ear + right_ear) / 2.0
    ear_nose_dist = np.linalg.norm(nose - mid_ear)

    left_shoulder = pt(11)
    right_shoulder = pt(12)
    mid_shoulder = (left_shoulder + right_shoulder) / 2.0

    up_vector = nose - mid_shoulder
    up_dist = np.linalg.norm(up_vector)
    up_unit = up_vector / (up_dist + 1e-6)
    head_top = nose + up_unit * (max(ear_nose_dist * 2.2, up_dist * 0.42))

    left_hip = pt(23)
    right_hip = pt(24)
    mid_hip = (left_hip + right_hip) / 2.0

    left_knee = pt(25)
    right_knee = pt(26)
    left_ankle = pt(27)
    right_ankle = pt(28)
    left_heel = pt(29)
    right_heel = pt(30)

    seg_head_torso = np.linalg.norm(mid_shoulder - head_top)
    seg_torso = np.linalg.norm(mid_hip - mid_shoulder)

    left_leg_len = (np.linalg.norm(left_knee - left_hip) + 
                    np.linalg.norm(left_ankle - left_knee) + 
                    np.linalg.norm(left_heel - left_ankle))
    
    right_leg_len = (np.linalg.norm(right_knee - right_hip) + 
                     np.linalg.norm(right_ankle - right_knee) + 
                     np.linalg.norm(right_heel - right_ankle))

    avg_leg_len = (left_leg_len + right_leg_len) / 2.0
    total_len_px = seg_head_torso + seg_torso + avg_leg_len
    total_len_cm = total_len_px * cm_per_pixel

    avg_heel = (left_heel + right_heel) / 2.0
    straight_len_px = np.linalg.norm(avg_heel - head_top)
    straight_len_cm = straight_len_px * cm_per_pixel

    annotated = img_bgr.copy()

    points_to_draw = [
        (head_top, (0, 0, 255), "Top Head"),
        (mid_shoulder, (255, 100, 0), "Shoulder"),
        (mid_hip, (255, 0, 255), "Hip"),
        (left_knee, (0, 255, 0), ""),
        (right_knee, (0, 255, 0), ""),
        (left_heel, (0, 255, 255), "L. Heel"),
        (right_heel, (0, 255, 255), "R. Heel"),
    ]

    lines = [
        (head_top, mid_shoulder, (0, 0, 255), 3),
        (mid_shoulder, mid_hip, (255, 120, 0), 3),
        (mid_hip, left_knee, (0, 200, 0), 3),
        (left_knee, left_ankle, (0, 200, 0), 3),
        (left_ankle, left_heel, (0, 220, 220), 3),
        (mid_hip, right_knee, (0, 200, 0), 3),
        (right_knee, right_ankle, (0, 200, 0), 3),
        (right_ankle, right_heel, (0, 220, 220), 3),
    ]

    for p1, p2, color, thickness in lines:
        cv2.line(annotated, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), color, thickness, cv2.LINE_AA)

    for p, color, label in points_to_draw:
        cx, cy = int(p[0]), int(p[1])
        cv2.circle(annotated, (cx, cy), 6, color, -1, cv2.LINE_AA)
        cv2.circle(annotated, (cx, cy), 8, (255, 255, 255), 1, cv2.LINE_AA)
        if label:
            cv2.putText(annotated, label, (cx + 10, cy + 4), cv2.FONT_HERSHEY_DUPLEX, 0.45, (20, 20, 20), 2, cv2.LINE_AA)
            cv2.putText(annotated, label, (cx + 10, cy + 4), cv2.FONT_HERSHEY_DUPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    # Info HUD Overlay
    hud_x, hud_y, hud_w, hud_h = 20, 20, 430, 140
    overlay = annotated.copy()
    cv2.rectangle(overlay, (hud_x, hud_y), (hud_x + hud_w, hud_y + hud_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.8, annotated, 0.2, 0, annotated)
    cv2.rectangle(annotated, (hud_x, hud_y), (hud_x + hud_w, hud_y + hud_h), (0, 200, 255), 1)

    cv2.putText(annotated, "MEDIA PIPE BABY HEIGHT ESTIMATOR", (hud_x + 14, hud_y + 26),
                cv2.FONT_HERSHEY_DUPLEX, 0.5, (0, 220, 255), 1, cv2.LINE_AA)
    
    cv2.putText(annotated, f"Scale: Max dim = {real_world_max_dimension_meters:.2f} m ({max_dim_px} px)", 
                (hud_x + 14, hud_y + 52), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)

    cv2.putText(annotated, f"Estimated Height (Segmented): {total_len_cm:.2f} cm", 
                (hud_x + 14, hud_y + 82), cv2.FONT_HERSHEY_DUPLEX, 0.58, (50, 255, 100), 2, cv2.LINE_AA)

    cv2.putText(annotated, f"Straight (Euclidean): {straight_len_cm:.2f} cm", 
                (hud_x + 14, hud_y + 110), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 220, 255), 1, cv2.LINE_AA)

    return {
        "segmented_height_cm": float(total_len_cm),
        "straight_height_cm": float(straight_len_cm),
        "annotated_bgr": annotated
    }

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/sample", methods=["GET"])
def get_sample():
    sample_path = r"C:\Users\arief\.gemini\antigravity-ide\brain\8dc935e2-c6c6-42f6-bf3e-a553e9fd223f\baby_fullbody_lying_1790114773945.jpg"
    if not os.path.exists(sample_path):
        return jsonify({"error": "Sample image not found"}), 404
    with open(sample_path, "rb") as f:
        b64_str = base64.b64encode(f.read()).decode("utf-8")
    return jsonify({"base64": b64_str})

@app.route("/api/detect", methods=["POST"])
def detect_endpoint():
    data = request.json or {}
    b64_img = data.get("image", "")
    scale_m = float(data.get("scale_meters", 1.0))

    if "," in b64_img:
        b64_img = b64_img.split(",")[1]

    img_bytes = base64.b64decode(b64_img)
    np_arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if img is None:
        return jsonify({"success": False, "error": "Invalid image data"}), 400

    result = process_pose(img, scale_m)
    if result is None:
        return jsonify({"success": False, "error": "No pose detected"}), 200

    _, buffer = cv2.imencode(".jpg", result["annotated_bgr"])
    out_b64 = base64.b64encode(buffer).decode("utf-8")

    return jsonify({
        "success": True,
        "segmented_height_cm": result["segmented_height_cm"],
        "straight_height_cm": result["straight_height_cm"],
        "annotated_image": out_b64
    })

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
