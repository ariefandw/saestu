#!/usr/bin/env python3
"""
Saestu MediaPipe Pose - Baby Height (Length) Estimator
Estimates baby body length from top-down photo assuming the maximum image dimension = max_dim_cm (default 100.0 cm).
Supports MediaPipe 1.0+ Tasks API with auto-download of model task file if needed.
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

def estimate_baby_length(image_path: str, max_dim_cm: float = 100.0, output_annotated_path: str = None):
    if not os.path.exists(image_path):
        return {"success": False, "error": f"Image file not found: {image_path}"}

    try:
        import cv2
    except ImportError:
        return {"success": False, "error": "cv2 (opencv-python) is not installed"}

    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
    except ImportError as e:
        return {"success": False, "error": f"mediapipe tasks import failed: {e}"}

    model_path, err = ensure_model_file()
    if err:
        return {"success": False, "error": err}

    img = cv2.imread(image_path)
    if img is None:
        return {"success": False, "error": "Failed to decode image"}

    h, w, _ = img.shape
    max_dim_px = max(h, w)
    if max_dim_px <= 0:
        return {"success": False, "error": "Invalid image dimensions"}

    ppm = max_dim_px / max_dim_cm  # pixels per centimeter

    # Configure PoseLandmarker
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
                "error": "No baby pose landmarks detected in photo",
                "width_px": w,
                "height_px": h,
                "ppm": round(ppm, 2)
            }

        lm = detection_result.pose_landmarks[0]

        def get_pt(idx):
            l = lm[idx]
            vis = getattr(l, 'visibility', 1.0)
            return np.array([l.x * w, l.y * h]), vis

        # Key landmark indices (PoseLandmark)
        # 0: Nose, 2: L Eye, 5: R Eye, 7: L Ear, 8: R Ear
        # 11: L Shoulder, 12: R Shoulder
        # 23: L Hip, 24: R Hip
        # 25: L Knee, 26: R Knee
        # 27: L Ankle, 28: R Ankle
        # 29: L Heel, 30: R Heel

        nose, v_nose = get_pt(0)
        l_eye, v_leye = get_pt(2)
        r_eye, v_reye = get_pt(5)
        l_ear, v_lear = get_pt(7)
        r_ear, v_rear = get_pt(8)

        # Crown (top of head) calculation
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

        # Left Leg chain
        l_knee, v_lknee = get_pt(25)
        l_ankle, v_lankle = get_pt(27)
        l_heel, v_lheel = get_pt(29)

        # Right Leg chain
        r_knee, v_rknee = get_pt(26)
        r_ankle, v_rankle = get_pt(28)
        r_heel, v_rheel = get_pt(30)

        # Segment lengths
        seg_crown_to_shoulder = float(np.linalg.norm(crown - mid_shoulder))
        seg_shoulder_to_hip = float(np.linalg.norm(mid_shoulder - mid_hip))

        # Left leg segments
        l_leg_len = (
            float(np.linalg.norm(mid_hip - l_knee)) +
            float(np.linalg.norm(l_knee - l_ankle)) +
            float(np.linalg.norm(l_ankle - l_heel))
        )

        # Right leg segments
        r_leg_len = (
            float(np.linalg.norm(mid_hip - r_knee)) +
            float(np.linalg.norm(r_knee - r_ankle)) +
            float(np.linalg.norm(r_ankle - r_heel))
        )

        l_conf = (v_lknee + v_lankle + v_lheel) / 3.0
        r_conf = (v_rknee + v_rankle + v_rheel) / 3.0

        # Use the longer leg chain (babies fold knees, longer chain represents full extension)
        chosen_leg_len = max(l_leg_len, r_leg_len)
        chosen_leg_side = "left" if chosen_leg_len == l_leg_len else "right"

        total_px = seg_crown_to_shoulder + seg_shoulder_to_hip + chosen_leg_len
        calculated_length_cm = round(total_px / ppm, 1)

        annotated_saved = False
        if output_annotated_path:
            annotated = img.copy()
            # Draw skeletal lines
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

            # Banner OSD
            osd_text = f"TB (MediaPipe): {calculated_length_cm} cm | Scale: {max_dim_cm}cm ({ppm:.1f} px/cm)"
            cv2.rectangle(annotated, (10, 10), (min(w - 10, 620), 50), (15, 23, 42), -1)
            cv2.putText(annotated, osd_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (16, 185, 129), 2, cv2.LINE_AA)

            cv2.imwrite(output_annotated_path, annotated)
            annotated_saved = True

        avg_confidence = float(np.mean([v_nose, v_lsh, v_rsh, v_lhip, v_rhip, l_conf, r_conf]))

        return {
            "success": True,
            "length_cm": calculated_length_cm,
            "confidence": round(avg_confidence, 3),
            "ppm": round(ppm, 2),
            "segments_px": {
                "crown_to_shoulder": round(seg_crown_to_shoulder, 1),
                "shoulder_to_hip": round(seg_shoulder_to_hip, 1),
                "leg_length": round(chosen_leg_len, 1),
                "leg_side": chosen_leg_side
            },
            "annotated_image": output_annotated_path if annotated_saved else None
        }

def main():
    parser = argparse.ArgumentParser(description="Estimate baby length via MediaPipe Pose landmarks")
    parser.add_argument("--image", required=True, help="Path to input photo")
    parser.add_argument("--max-dim-cm", type=float, default=100.0, help="Real-world length (in cm) of the maximum image dimension (default: 100.0)")
    parser.add_argument("--output-annotated", default=None, help="Optional path to write annotated photo")
    args = parser.parse_args()

    result = estimate_baby_length(args.image, args.max_dim_cm, args.output_annotated)
    print(json.dumps(result, indent=2))
    if not result.get("success"):
        sys.exit(1)

if __name__ == "__main__":
    main()
