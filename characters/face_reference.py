from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

MODEL_URL = "https://huggingface.co/pollen-robotics/face_detection_yunet_2023mar/resolve/main/face_detection_yunet_2023mar.onnx?download=true"
MODEL_PATH = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"


def _download_model() -> Path | None:
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 100_000:
        return MODEL_PATH
    try:
        from urllib.request import urlopen
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(MODEL_URL, timeout=20) as response:
            data = response.read()
        if len(data) < 100_000:
            return None
        MODEL_PATH.write_bytes(data)
        return MODEL_PATH
    except Exception:
        return None


def _detect_face(image: Image.Image) -> tuple[float, float, float, float] | None:
    """Return the largest face bbox as x, y, w, h.

    Uses OpenCV YuNet when available. It deliberately does not use
    CascadeClassifier because some OpenCV builds do not expose it.
    """
    try:
        import cv2  # type: ignore
        detector_cls = getattr(cv2, "FaceDetectorYN", None)
        if detector_cls is None:
            return None
        model = _download_model()
        if model is None:
            return None

        rgb = image.convert("RGB")
        import numpy as np  # type: ignore
        frame = np.asarray(rgb)[:, :, ::-1].copy()
        h, w = frame.shape[:2]
        detector = detector_cls.create(str(model), "", (320, 320), 0.60, 0.30, 5000)
        detector.setInputSize((w, h))
        _, faces = detector.detect(frame)
        if faces is None or len(faces) == 0:
            return None
        best = max(faces, key=lambda f: float(f[2] * f[3] * f[14]))
        return tuple(float(v) for v in best[:4])  # type: ignore[return-value]
    except Exception:
        return None


def _fallback_bbox(image: Image.Image) -> tuple[float, float, float, float]:
    """Portrait fallback for environments without a usable OpenCV detector."""
    w, h = image.size
    # Conservative central portrait region; detection is preferred whenever available.
    bw = w * 0.50
    bh = h * 0.56
    x = (w - bw) / 2
    y = h * 0.15
    return x, y, bw, bh


def _crop_square(image: Image.Image, bbox: tuple[float, float, float, float], scale: float) -> Image.Image:
    w, h = image.size
    x, y, bw, bh = bbox
    side = max(bw * scale, bh * scale)
    cx = x + bw * 0.50
    cy = y + bh * 0.47
    left = cx - side / 2
    top = cy - side / 2
    # Shift the crop back inside the source without changing its size where possible.
    left = max(0, min(left, w - side))
    top = max(0, min(top, h - side))
    right = min(w, left + side)
    bottom = min(h, top + side)
    crop = image.crop((int(left), int(top), int(right), int(bottom)))
    return ImageOps.fit(crop, (512, 512), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def prepare_face_references(image_bytes: bytes) -> tuple[bytes, bytes]:
    """Create tight and wider 512x512 face references from the original image.

    Returns (tight_reference_jpg, full_reference_jpg). No AI generation is used;
    both images contain only pixels from the user's original reference.
    """
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    bbox = _detect_face(image)
    if bbox is None:
        bbox = _fallback_bbox(image)

    tight = _crop_square(image, bbox, 1.35)
    full = _crop_square(image, bbox, 1.65)

    tight_buf = io.BytesIO()
    full_buf = io.BytesIO()
    tight.save(tight_buf, format="JPEG", quality=95, subsampling=0)
    full.save(full_buf, format="JPEG", quality=95, subsampling=0)
    return tight_buf.getvalue(), full_buf.getvalue()


def prepare_face_reference(image_bytes: bytes) -> bytes:
    """Backward-compatible helper returning the tight face reference."""
    return prepare_face_references(image_bytes)[0]
