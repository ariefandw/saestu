#!/usr/bin/env python3
"""
Saestu Multi-Method Baby Length (Height) Estimator
Supports 3 comparative methods for academic research & clinical validation:
  1. mediapipe       : Deep Learning Pose Landmarker (BlazePose 33 joints)
  2. contour_caliper : OpenCV Adaptive Silhouette & Morphological Caliper
  3. aruco_marker    : Physical ArUco Fiducial Marker Metrology (Metric Scale)
"""

import sys
import os
import json
import argparse
import urllib.request
import numpy as np

MODEL_FILENAME = "pose_landmarker_full.task"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"


def ensure_model_file():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(script_dir, MODEL_FILENAME)
    if not os.path.exists(model_path):
        try:
            print(f"Downloading {MODEL_FILENAME}...", file=sys.stderr)
            urllib.request.urlretrieve(MODEL_URL, model_path)
        except Exception as e:
            return None, f"Failed to download model: {e}"
    return model_path, None


def draw_caliper_lines(annotated, pt_top, pt_bottom, pt_center, angle_deg, color=(0, 255, 255), bar_len=60):
    """Menggambar garis pengukur (digital caliper) dengan bilah penahan di kepala dan kaki."""
    # Garis sumbu utama
    cv2 = sys.modules.get("cv2")
    cv2.line(annotated, (int(pt_top[0]), int(pt_top[1])), (int(pt_bottom[0]), int(pt_bottom[1])), color, 3)

    # Vektor tegak lurus buat bilah caliper
    rad = np.radians(angle_deg + 90)
    dx = np.cos(rad) * (bar_len / 2.0)
    dy = np.sin(rad) * (bar_len / 2.0)

    # Bilah atas (Kepala)
    t1 = (int(pt_top[0] - dx), int(pt_top[1] - dy))
    t2 = (int(pt_top[0] + dx), int(pt_top[1] + dy))
    cv2.line(annotated, t1, t2, (255, 0, 255), 4)
    cv2.circle(annotated, (int(pt_top[0]), int(pt_top[1])), 6, (255, 0, 255), -1)

    # Bilah bawah (Tumit)
    b1 = (int(pt_bottom[0] - dx), int(pt_bottom[1] - dy))
    b2 = (int(pt_bottom[0] + dx), int(pt_bottom[1] + dy))
    cv2.line(annotated, b1, b2, (0, 165, 255), 4)
    cv2.circle(annotated, (int(pt_bottom[0]), int(pt_bottom[1])), 6, (0, 165, 255), -1)


# ==============================================================================
# METHOD 1: MediaPipe Pose Landmark (Deep Learning Baseline)
# ==============================================================================
def estimate_mediapipe(img, max_dim_cm=100.0, output_annotated_path=None):
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
    except ImportError as e:
        return {"success": False, "error": f"MediaPipe import failed: {e}"}

    model_path, err = ensure_model_file()
    if err:
        return {"success": False, "error": err}

    h, w, _ = img.shape
    max_dim_px = max(h, w)
    ppm = max_dim_px / max_dim_cm

    base_options = mp_python.BaseOptions(model_asset_path=model_path)
    options = mp_vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=mp_vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.3,
        min_pose_presence_confidence=0.3
    )

    with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_img)
        detection_result = landmarker.detect(mp_image)

        if not detection_result.pose_landmarks or len(detection_result.pose_landmarks) == 0:
            return {
                "success": False,
                "error": "Pose landmark bayi tidak terdeteksi oleh MediaPipe. Coba ratakan posisi bayi atau gunakan metode Siluet Kontur.",
                "width_px": w,
                "height_px": h,
                "ppm": round(float(ppm), 2)
            }

        lm = detection_result.pose_landmarks[0]

        def get_pt(idx):
            l = lm[idx]
            vis = getattr(l, 'visibility', 1.0)
            return np.array([l.x * w, l.y * h]), vis

        nose, v_nose = get_pt(0)
        l_eye, v_leye = get_pt(2)
        r_eye, v_reye = get_pt(5)
        l_ear, v_lear = get_pt(7)
        r_ear, v_rear = get_pt(8)

        # Ubun-ubun (Crown)
        mid_ear = (l_ear + r_ear) / 2.0
        head_vec = nose - mid_ear
        norm_head = np.linalg.norm(head_vec)
        if norm_head > 1.0:
            crown = nose + (head_vec / norm_head) * (norm_head * 0.9)
        else:
            mid_eye = (l_eye + r_eye) / 2.0
            eye_nose_vec = nose - mid_eye
            norm_eye = np.linalg.norm(eye_nose_vec)
            if norm_eye > 0.5:
                crown = mid_eye - (eye_nose_vec / norm_eye) * (norm_eye * 1.5)
            else:
                crown = nose

        # Torso
        l_sh, v_lsh = get_pt(11)
        r_sh, v_rsh = get_pt(12)
        mid_shoulder = (l_sh + r_sh) / 2.0

        l_hip, v_lhip = get_pt(23)
        r_hip, v_rhip = get_pt(24)
        mid_hip = (l_hip + r_hip) / 2.0

        # Kaki Kiri & Kanan
        l_knee, v_lknee = get_pt(25)
        l_ankle, v_lankle = get_pt(27)
        l_heel, v_lheel = get_pt(29)

        r_knee, v_rknee = get_pt(26)
        r_ankle, v_rankle = get_pt(28)
        r_heel, v_rheel = get_pt(30)

        seg_crown_to_shoulder = float(np.linalg.norm(crown - mid_shoulder))
        seg_shoulder_to_hip = float(np.linalg.norm(mid_shoulder - mid_hip))

        l_leg_len = (
            float(np.linalg.norm(mid_hip - l_knee)) +
            float(np.linalg.norm(l_knee - l_ankle)) +
            float(np.linalg.norm(l_ankle - l_heel))
        )
        r_leg_len = (
            float(np.linalg.norm(mid_hip - r_knee)) +
            float(np.linalg.norm(r_knee - r_ankle)) +
            float(np.linalg.norm(r_ankle - r_heel))
        )

        chosen_leg_len = max(l_leg_len, r_leg_len)
        chosen_leg_side = "left" if chosen_leg_len == l_leg_len else "right"

        total_px = seg_crown_to_shoulder + seg_shoulder_to_hip + chosen_leg_len
        calculated_length_cm = round(float(total_px / ppm), 1)

        annotated_saved = False
        if output_annotated_path:
            annotated = img.copy()
            lines = [
                (crown, mid_shoulder, (0, 255, 255)),
                (mid_shoulder, mid_hip, (0, 255, 0)),
                (mid_hip, l_knee if chosen_leg_side == "left" else r_knee, (255, 128, 0)),
                (l_knee if chosen_leg_side == "left" else r_knee, l_ankle if chosen_leg_side == "left" else r_ankle, (255, 128, 0)),
                (l_ankle if chosen_leg_side == "left" else r_ankle, l_heel if chosen_leg_side == "left" else r_heel, (255, 128, 0)),
            ]
            for p1, p2, color in lines:
                cv2.line(annotated, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), color, 3)

            for idx in [0, 11, 12, 23, 24, 25, 26, 27, 28, 29, 30]:
                pt, _ = get_pt(idx)
                cv2.circle(annotated, (int(pt[0]), int(pt[1])), 5, (0, 0, 255), -1)

            cv2.circle(annotated, (int(crown[0]), int(crown[1])), 6, (255, 0, 255), -1)

            osd_text = f"TB (MediaPipe Pose): {calculated_length_cm} cm | Scale: {max_dim_cm}cm ({ppm:.1f} px/cm)"
            cv2.rectangle(annotated, (10, 10), (min(w - 10, 680), 50), (15, 23, 42), -1)
            cv2.putText(annotated, osd_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (16, 185, 129), 2, cv2.LINE_AA)

            cv2.imwrite(output_annotated_path, annotated)
            annotated_saved = True

        l_conf = (v_lknee + v_lankle + v_lheel) / 3.0
        r_conf = (v_rknee + v_rankle + v_rheel) / 3.0
        avg_confidence = float(np.mean([v_nose, v_lsh, v_rsh, v_lhip, v_rhip, l_conf, r_conf]))

        return {
            "success": True,
            "method": "mediapipe",
            "method_name": "MediaPipe Pose (AI Keypoint)",
            "length_cm": calculated_length_cm,
            "confidence": round(float(avg_confidence), 3),
            "ppm": round(float(ppm), 2),
            "segments_px": {
                "crown_to_shoulder": round(seg_crown_to_shoulder, 1),
                "shoulder_to_hip": round(seg_shoulder_to_hip, 1),
                "leg_length": round(chosen_leg_len, 1),
                "leg_side": chosen_leg_side
            },
            "annotated_image": output_annotated_path if annotated_saved else None
        }


# ==============================================================================
# METHOD 2: Silhouette & Morphological Caliper (Computer Vision Kontur)
# ==============================================================================
def estimate_contour_caliper(img, max_dim_cm=100.0, output_annotated_path=None):
    try:
        import cv2
    except ImportError:
        return {"success": False, "error": "cv2 (opencv-python) is not installed"}

    h, w = img.shape[:2]
    max_dim_px = max(h, w)
    ppm = max_dim_px / max_dim_cm

    # Sample background color dari 4 pojok matras
    margin = max(10, min(30, int(min(h, w) * 0.04)))
    corners = [
        img[2:margin, 2:margin],
        img[2:margin, w-margin:w-2],
        img[h-margin:h-2, 2:margin],
        img[h-margin:h-2, w-margin:w-2]
    ]
    bg_color = np.median(np.concatenate([c.reshape(-1, 3) for c in corners]), axis=0)

    diff = np.linalg.norm(img.astype(np.float32) - bg_color.astype(np.float32), axis=2)
    diff = np.clip(diff * (255.0 / (np.max(diff) + 1e-5)), 0, 255).astype(np.uint8)

    blurred = cv2.GaussianBlur(diff, (9, 9), 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {"success": False, "error": "Siluet tubuh bayi tidak terdeteksi dari latar belakang matras"}

    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < (h * w * 0.02):
        return {"success": False, "error": "Objek kontur terlalu kecil atau kontras dengan matras kurang jelas"}

    rect = cv2.minAreaRect(c)
    (center, (dim1, dim2), angle) = rect
    length_px = float(max(dim1, dim2))
    width_px = float(min(dim1, dim2))

    # Tentukan orientasi sudut sepanjang sisi terpanjang
    box = cv2.boxPoints(rect)
    box = np.int32(box)

    edge1 = np.linalg.norm(box[0] - box[1])
    edge2 = np.linalg.norm(box[1] - box[2])
    if edge1 > edge2:
        pt_top = (box[0] + box[3]) / 2.0
        pt_bottom = (box[1] + box[2]) / 2.0
        caliper_angle = np.degrees(np.arctan2(box[0][1] - box[3][1], box[0][0] - box[3][0]))
    else:
        pt_top = (box[0] + box[1]) / 2.0
        pt_bottom = (box[3] + box[2]) / 2.0
        caliper_angle = np.degrees(np.arctan2(box[0][1] - box[1][1], box[0][0] - box[1][0]))

    # Pastikan pt_top ada di posisi yang lebih atas (y lebih kecil)
    if pt_top[1] > pt_bottom[1]:
        pt_top, pt_bottom = pt_bottom, pt_top

    calculated_length_cm = round(float(length_px / ppm), 1)

    annotated_saved = False
    if output_annotated_path:
        annotated = img.copy()
        # Gambar garis siluet kontur
        cv2.drawContours(annotated, [c], -1, (0, 255, 255), 2)
        # Gambar kotak orientasi
        cv2.polylines(annotated, [box], True, (0, 200, 0), 1, cv2.LINE_AA)
        # Gambar caliper
        draw_caliper_lines(annotated, pt_top, pt_bottom, center, caliper_angle, color=(0, 255, 255), bar_len=int(width_px * 0.9))

        osd_text = f"TB (Siluet Kontur): {calculated_length_cm} cm | Scale: {max_dim_cm}cm ({ppm:.1f} px/cm)"
        cv2.rectangle(annotated, (10, 10), (min(w - 10, 680), 50), (15, 23, 42), -1)
        cv2.putText(annotated, osd_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (14, 165, 233), 2, cv2.LINE_AA)

        cv2.imwrite(output_annotated_path, annotated)
        annotated_saved = True

    return {
        "success": True,
        "method": "contour_caliper",
        "method_name": "Siluet Kontur & Morfologi (Bebas Landmark)",
        "length_cm": calculated_length_cm,
        "length_px": round(length_px, 1),
        "confidence": 0.88,
        "ppm": round(float(ppm), 2),
        "annotated_image": output_annotated_path if annotated_saved else None
    }


# ==============================================================================
# METHOD 3: ArUco Optical Metrology (Fiducial Marker Calibration)
# ==============================================================================
def estimate_aruco_metric(img, marker_size_cm=10.0, output_annotated_path=None):
    try:
        import cv2
    except ImportError:
        return {"success": False, "error": "cv2 (opencv-python) is not installed"}

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    dicts = [
        cv2.aruco.DICT_4X4_50,
        cv2.aruco.DICT_5X5_50,
        cv2.aruco.DICT_6X6_50,
        cv2.aruco.DICT_ARUCO_ORIGINAL
    ]

    found_corners = None
    found_id = None

    for d_type in dicts:
        aruco_dict = cv2.aruco.getPredefinedDictionary(d_type)
        params = cv2.aruco.DetectorParameters()
        detector = cv2.aruco.ArucoDetector(aruco_dict, params)
        corners, ids, _ = detector.detectMarkers(gray)
        if ids is not None and len(ids) > 0:
            found_corners = corners
            found_id = int(ids.flatten()[0])
            break

    if found_corners is None:
        return {
            "success": False,
            "error": "Marker ArUco tidak terdeteksi di foto. Letakkan marker fisik (misal 10x10 cm) di samping bayi dan pastikan tidak terhalang atau pantul cahaya."
        }

    c_marker = found_corners[0][0]
    side1 = np.linalg.norm(c_marker[0] - c_marker[1])
    side2 = np.linalg.norm(c_marker[1] - c_marker[2])
    side3 = np.linalg.norm(c_marker[2] - c_marker[3])
    side4 = np.linalg.norm(c_marker[3] - c_marker[0])
    avg_side_px = float((side1 + side2 + side3 + side4) / 4.0)

    if avg_side_px <= 5:
        return {"success": False, "error": "Marker ArUco terlalu kecil di foto untuk kalibrasi yang presisi"}

    ppm = float(avg_side_px / marker_size_cm)

    # Mask marker agar tidak terdeteksi sebagai tubuh bayi
    marker_mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillPoly(marker_mask, [np.int32(c_marker)], 255)
    kernel_dil = np.ones((25, 25), np.uint8)
    marker_mask = cv2.dilate(marker_mask, kernel_dil, iterations=2)

    margin = max(10, min(30, int(min(h, w) * 0.04)))
    corners_bg = [
        img[2:margin, 2:margin],
        img[2:margin, w-margin:w-2],
        img[h-margin:h-2, 2:margin],
        img[h-margin:h-2, w-margin:w-2]
    ]
    bg_color = np.median(np.concatenate([c_bg.reshape(-1, 3) for c_bg in corners_bg]), axis=0)

    diff = np.linalg.norm(img.astype(np.float32) - bg_color.astype(np.float32), axis=2)
    diff[marker_mask > 0] = 0
    diff = np.clip(diff * (255.0 / (np.max(diff) + 1e-5)), 0, 255).astype(np.uint8)

    blurred = cv2.GaussianBlur(diff, (9, 9), 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask[marker_mask > 0] = 0

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {"success": False, "error": "Marker ArUco terdeteksi, namun siluet tubuh bayi tidak terpisah dari matras"}

    c_baby = max(contours, key=cv2.contourArea)
    rect = cv2.minAreaRect(c_baby)
    (center, (dim1, dim2), angle) = rect
    length_px = float(max(dim1, dim2))
    width_px = float(min(dim1, dim2))

    box = cv2.boxPoints(rect)
    box = np.int32(box)

    edge1 = np.linalg.norm(box[0] - box[1])
    edge2 = np.linalg.norm(box[1] - box[2])
    if edge1 > edge2:
        pt_top = (box[0] + box[3]) / 2.0
        pt_bottom = (box[1] + box[2]) / 2.0
        caliper_angle = np.degrees(np.arctan2(box[0][1] - box[3][1], box[0][0] - box[3][0]))
    else:
        pt_top = (box[0] + box[1]) / 2.0
        pt_bottom = (box[3] + box[2]) / 2.0
        caliper_angle = np.degrees(np.arctan2(box[0][1] - box[1][1], box[0][0] - box[1][0]))

    if pt_top[1] > pt_bottom[1]:
        pt_top, pt_bottom = pt_bottom, pt_top

    calculated_length_cm = round(float(length_px / ppm), 1)

    annotated_saved = False
    if output_annotated_path:
        annotated = img.copy()
        # Gambar border ArUco
        cv2.polylines(annotated, [np.int32(c_marker)], True, (0, 0, 255), 3)
        marker_center = np.mean(c_marker, axis=0).astype(int)
        cv2.putText(annotated, f"ArUco #{found_id} ({marker_size_cm}cm)", (marker_center[0] - 50, marker_center[1] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        # Gambar kontur dan caliper
        cv2.drawContours(annotated, [c_baby], -1, (0, 255, 255), 2)
        cv2.polylines(annotated, [box], True, (0, 200, 0), 1, cv2.LINE_AA)
        draw_caliper_lines(annotated, pt_top, pt_bottom, center, caliper_angle, color=(0, 255, 255), bar_len=int(width_px * 0.9))

        osd_text = f"TB (ArUco Optical): {calculated_length_cm} cm | Marker ID #{found_id} ({ppm:.1f} px/cm)"
        cv2.rectangle(annotated, (10, 10), (min(w - 10, 720), 50), (15, 23, 42), -1)
        cv2.putText(annotated, osd_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (168, 85, 247), 2, cv2.LINE_AA)

        cv2.imwrite(output_annotated_path, annotated)
        annotated_saved = True

    return {
        "success": True,
        "method": "aruco_marker",
        "method_name": "ArUco Metrologi Fisik (Optical Fiducial Marker)",
        "length_cm": calculated_length_cm,
        "length_px": round(length_px, 1),
        "ppm": round(float(ppm), 2),
        "marker_id": found_id,
        "marker_side_px": round(avg_side_px, 1),
        "marker_size_cm": marker_size_cm,
        "confidence": 0.97,
        "annotated_image": output_annotated_path if annotated_saved else None
    }


# ==============================================================================
# MAIN ROUTER
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="Saestu Multi-Method Baby Length Estimator")
    parser.add_argument("--image", required=True, help="Path to input photo")
    parser.add_argument("--method", default="mediapipe", choices=["mediapipe", "contour_caliper", "aruco_marker"],
                        help="Metode estimasi: mediapipe | contour_caliper | aruco_marker (default: mediapipe)")
    parser.add_argument("--max-dim-cm", type=float, default=100.0,
                        help="Panjang sisi terpanjang frame pada matras (cm, default: 100.0)")
    parser.add_argument("--marker-size-cm", type=float, default=10.0,
                        help="Ukuran fisik marker ArUco (cm, default: 10.0)")
    parser.add_argument("--output-annotated", default=None, help="Optional path to write annotated photo")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(json.dumps({"success": False, "error": f"Image file not found: {args.image}"}))
        sys.exit(1)

    try:
        import cv2
    except ImportError:
        print(json.dumps({"success": False, "error": "OpenCV (cv2) is not installed"}))
        sys.exit(1)

    img = cv2.imread(args.image)
    if img is None:
        print(json.dumps({"success": False, "error": "Failed to decode image"}))
        sys.exit(1)

    if args.method == "mediapipe":
        result = estimate_mediapipe(img, max_dim_cm=args.max_dim_cm, output_annotated_path=args.output_annotated)
    elif args.method == "contour_caliper":
        result = estimate_contour_caliper(img, max_dim_cm=args.max_dim_cm, output_annotated_path=args.output_annotated)
    elif args.method == "aruco_marker":
        result = estimate_aruco_metric(img, marker_size_cm=args.marker_size_cm, output_annotated_path=args.output_annotated)
    else:
        result = {"success": False, "error": f"Metode tidak dikenal: {args.method}"}

    print(json.dumps(result, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
