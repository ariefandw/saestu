import os
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

def measure_baby_height(image_path, output_path, real_world_max_dimension_meters=1.0):
    # Load image with OpenCV
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        raise FileNotFoundError(f"Cannot load image: {image_path}")

    h, w, _ = img_bgr.shape
    
    # Scale calibration: maximum dimension (max(w, h)) = 1 meter
    max_dim_px = max(h, w)
    meters_per_pixel = real_world_max_dimension_meters / max_dim_px
    cm_per_pixel = meters_per_pixel * 100.0

    # MediaPipe setup
    model_path = "pose_landmarker.task"
    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        output_segmentation_masks=False
    )
    detector = vision.PoseLandmarker.create_from_options(options)

    # Convert to MediaPipe Image
    mp_image = mp.Image.create_from_file(image_path)
    detection_result = detector.detect(mp_image)

    if not detection_result.pose_landmarks:
        print("[-] No pose detected!")
        return None

    landmarks = detection_result.pose_landmarks[0]

    # Landmark indices for MediaPipe Pose:
    # 0: nose
    # 7: left_ear, 8: right_ear
    # 11: left_shoulder, 12: right_shoulder
    # 23: left_hip, 24: right_hip
    # 25: left_knee, 26: right_knee
    # 27: left_ankle, 28: right_ankle
    # 29: left_heel, 30: right_heel
    # 31: left_foot_index, 32: right_foot_index

    def pt(idx):
        lm = landmarks[idx]
        return np.array([lm.x * w, lm.y * h])

    # Head top estimation:
    # Nose to mid-ear distance can help estimate the top of the cranium, or simply top of head based on nose - (ear_y - nose_y)
    nose = pt(0)
    left_ear = pt(7)
    right_ear = pt(8)
    mid_ear = (left_ear + right_ear) / 2.0
    
    # Cranium estimation offset:
    # MediaPipe pose landmarks stop at nose / eyes / ears. Infants have relatively large craniums.
    # We estimate top of head by extending vector from shoulder-center through mid-ear / nose.
    ear_nose_dist = np.linalg.norm(nose - mid_ear)
    left_shoulder = pt(11)
    right_shoulder = pt(12)
    mid_shoulder = (left_shoulder + right_shoulder) / 2.0
    
    # Vector from torso up to mid-face
    up_vector = nose - mid_shoulder
    up_dist = np.linalg.norm(up_vector)
    up_unit = up_vector / (up_dist + 1e-6)
    
    # Cranium top is approx 0.85x nose-to-shoulder height above nose (or ~1.3x ear-to-nose offset above forehead)
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

    # Segment lengths along anatomical chain:
    # 1. Head top to Mid-Shoulder
    seg_head_torso = np.linalg.norm(mid_shoulder - head_top)
    
    # 2. Mid-Shoulder to Mid-Hip
    seg_torso = np.linalg.norm(mid_hip - mid_shoulder)

    # 3. Legs: compute both left and right chain, take the average or the clearer/longer one
    # Left leg: Hip -> Knee -> Ankle -> Heel
    left_leg_len = (np.linalg.norm(left_knee - left_hip) + 
                    np.linalg.norm(left_ankle - left_knee) + 
                    np.linalg.norm(left_heel - left_ankle))
    
    # Right leg: Hip -> Knee -> Ankle -> Heel
    right_leg_len = (np.linalg.norm(right_knee - right_hip) + 
                     np.linalg.norm(right_ankle - right_knee) + 
                     np.linalg.norm(right_heel - right_ankle))

    avg_leg_len = (left_leg_len + right_leg_len) / 2.0

    # Total body length along spine & legs (anatomical contour)
    total_len_px = seg_head_torso + seg_torso + avg_leg_len
    total_len_cm = total_len_px * cm_per_pixel

    # Straight line (Bounding / Crown-to-Heels) for comparison
    avg_heel = (left_heel + right_heel) / 2.0
    straight_len_px = np.linalg.norm(avg_heel - head_top)
    straight_len_cm = straight_len_px * cm_per_pixel

    # Visualization
    annotated = img_bgr.copy()

    # Draw key landmarks
    points_to_draw = [
        (head_top, (0, 0, 255), "Top Head"),
        (mid_shoulder, (255, 100, 0), "Shoulder"),
        (mid_hip, (255, 0, 255), "Hip"),
        (left_knee, (0, 255, 0), ""),
        (right_knee, (0, 255, 0), ""),
        (left_heel, (0, 255, 255), "L. Heel"),
        (right_heel, (0, 255, 255), "R. Heel"),
    ]

    # Draw anatomical skeleton lines
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
    hud_x, hud_y, hud_w, hud_h = 24, 24, 460, 160
    overlay = annotated.copy()
    cv2.rectangle(overlay, (hud_x, hud_y), (hud_x + hud_w, hud_y + hud_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.75, annotated, 0.25, 0, annotated)
    cv2.rectangle(annotated, (hud_x, hud_y), (hud_x + hud_w, hud_y + hud_h), (0, 200, 255), 1)

    cv2.putText(annotated, "MEDIA PIPE BABY HEIGHT ESTIMATOR", (hud_x + 16, hud_y + 30),
                cv2.FONT_HERSHEY_DUPLEX, 0.55, (0, 220, 255), 1, cv2.LINE_AA)
    
    cv2.putText(annotated, f"Image Scale: Max dimension = {real_world_max_dimension_meters:.1f} m ({max_dim_px} px)", 
                (hud_x + 16, hud_y + 58), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

    cv2.putText(annotated, f"Pixel Ratio: {cm_per_pixel:.4f} cm/px", 
                (hud_x + 16, hud_y + 82), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

    cv2.putText(annotated, f"Estimated Height (Segmented): {total_len_cm:.2f} cm", 
                (hud_x + 16, hud_y + 115), cv2.FONT_HERSHEY_DUPLEX, 0.65, (50, 255, 100), 2, cv2.LINE_AA)

    cv2.putText(annotated, f"Crown-to-Heel (Euclidean): {straight_len_cm:.2f} cm", 
                (hud_x + 16, hud_y + 142), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 255), 1, cv2.LINE_AA)

    cv2.imwrite(output_path, annotated)
    print(f"[+] Processed image successfully saved to: {output_path}")
    print(f"[+] Total Segmented Height: {total_len_cm:.2f} cm | Straight: {straight_len_cm:.2f} cm")
    return total_len_cm

if __name__ == "__main__":
    test_img = r"C:\Users\arief\.gemini\antigravity-ide\brain\8dc935e2-c6c6-42f6-bf3e-a553e9fd223f\baby_fullbody_lying_1790114773945.jpg"
    out_img = r"C:\Users\arief\.gemini\antigravity-ide\brain\8dc935e2-c6c6-42f6-bf3e-a553e9fd223f\baby_height_detected.jpg"
    measure_baby_height(test_img, out_img, real_world_max_dimension_meters=1.0)
