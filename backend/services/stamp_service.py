import cv2
import numpy as np
from services.ocr_service import extract_page_text


def detect_stamps(image):
    """Candidatos con contorno cerrado y tinta de color. Coordenadas normalizadas."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 65, 35), (179, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = mask.shape
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if not (.0008 <= area / (width * height) <= .22 and .55 <= w / h <= 2.8):
            continue
        if min(w, h) < 28 or cv2.contourArea(contour) < .52 * area:
            continue
        ink = np.count_nonzero(mask[y:y+h, x:x+w]) / area
        if not .06 <= ink <= .60:
            continue
        boxes.append((x, y, w, h, contour))
    stamps = []
    for x, y, w, h, contour in sorted(boxes, key=lambda b: (b[1], b[0]))[:12]:
        crop = image[y:y+h, x:x+w].copy()
        border = contour - np.array([[[x, y]]], dtype=contour.dtype)
        cv2.drawContours(crop, [border], -1, (255, 255, 255), max(5, round(min(w, h) * .12)))
        crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=(255,255,255))
        read = extract_page_text(crop, optional=True)
        stamps.append({"bbox": [x/width, y/height, (x+w)/width, (y+h)/height],
                       "text": read["text"], "confidence": read["confidence"], "requires_review": True})
    return stamps
