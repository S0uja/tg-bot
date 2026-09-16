from __future__ import annotations

from collections import deque
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


SIZE = (512, 768)


def _resize_rgb(data: bytes) -> Image.Image:
    with Image.open(BytesIO(data)) as im:
        return im.convert("RGB").resize(SIZE, Image.Resampling.LANCZOS)


def _resize_gray(data: bytes) -> Image.Image:
    with Image.open(BytesIO(data)) as im:
        return im.convert("L").resize(SIZE, Image.Resampling.LANCZOS)


def _border_color(image: Image.Image) -> tuple[float, float, float]:
    pix = image.load()
    w, h = image.size
    samples = []
    step = max(1, min(w, h) // 128)
    for x in range(0, w, step):
        samples.append(pix[x, 0])
        samples.append(pix[x, h - 1])
    for y in range(0, h, step):
        samples.append(pix[0, y])
        samples.append(pix[w - 1, y])
    samples.sort(key=lambda p: sum(p))
    # Median per channel is more robust than one corner in studio scenes.
    n = len(samples)
    return (
        sorted(p[0] for p in samples)[n // 2],
        sorted(p[1] for p in samples)[n // 2],
        sorted(p[2] for p in samples)[n // 2],
    )


def _color_foreground(image: Image.Image) -> Image.Image:
    """Conservative foreground estimate from border/background appearance."""
    bg = _border_color(image)
    pix = image.load()
    w, h = image.size
    # Start conservative; the skeleton anchor below protects the person.
    threshold = 48.0
    mask = Image.new("L", image.size, 0)
    out = mask.load()
    for y in range(h):
        for x in range(w):
            r, g, b = pix[x, y]
            d = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
            if d > threshold:
                out[x, y] = 255
    # Close small holes/edge gaps without making the mask enormous.
    return mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))


def _skeleton_anchor(openpose: Image.Image) -> Image.Image:
    # OpenPose images are black background with colored/bright limbs.
    anchor = openpose.point(lambda p: 255 if p > 8 else 0)
    # Expand joints/limbs enough to bridge into the actual body silhouette.
    return (
        anchor
        .filter(ImageFilter.MaxFilter(31))
        .filter(ImageFilter.MaxFilter(31))
    )


def _largest_component(mask: Image.Image, anchor: Image.Image) -> Image.Image:
    """Keep the foreground component that contains the OpenPose anchor."""
    w, h = mask.size
    mp = mask.load()
    ap = anchor.load()

    # Add anchor as guaranteed foreground.
    work = bytearray(w * h)
    for y in range(h):
        row = y * w
        for x in range(w):
            if mp[x, y] or ap[x, y]:
                work[row + x] = 1

    # Find all anchor pixels and flood-fill their connected union.
    seeds = deque()
    seen = bytearray(w * h)
    for y in range(h):
        row = y * w
        for x in range(w):
            idx = row + x
            if work[idx] and ap[x, y] and not seen[idx]:
                seen[idx] = 1
                seeds.append((x, y))

    while seeds:
        x, y = seeds.popleft()
        if x:
            idx = y * w + (x - 1)
            if work[idx] and not seen[idx]:
                seen[idx] = 1
                seeds.append((x - 1, y))
        if x + 1 < w:
            idx = y * w + (x + 1)
            if work[idx] and not seen[idx]:
                seen[idx] = 1
                seeds.append((x + 1, y))
        if y:
            idx = (y - 1) * w + x
            if work[idx] and not seen[idx]:
                seen[idx] = 1
                seeds.append((x, y - 1))
        if y + 1 < h:
            idx = (y + 1) * w + x
            if work[idx] and not seen[idx]:
                seen[idx] = 1
                seeds.append((x, y + 1))

    # If the conservative color mask is fragmented, anchor dilation still gives
    # a useful person-only region. Smooth the final silhouette slightly.
    out = Image.new("L", (w, h), 0)
    op = out.load()
    for y in range(h):
        row = y * w
        for x in range(w):
            if seen[row + x]:
                op[x, y] = 255
    return out.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))


def make_person_depth(
    original_bytes: bytes,
    depth_bytes: bytes,
    openpose_bytes: bytes,
) -> bytes:
    """Create an experimental person-only depth map.

    The existing depth values inside a pose-guided foreground silhouette are
    preserved. Background depth is neutralized to mid-gray so the Depth ControlNet
    receives much less scene geometry.
    """
    original = _resize_rgb(original_bytes)
    depth = _resize_gray(depth_bytes)
    openpose = _resize_rgb(openpose_bytes).convert("L")

    color_fg = _color_foreground(original)
    anchor = _skeleton_anchor(openpose)
    combined = ImageChops.lighter(color_fg, anchor)
    person = _largest_component(combined, anchor)

    # Keep only a soft margin around the person and neutralize everything else.
    person = person.filter(ImageFilter.GaussianBlur(2.0))
    neutral = Image.new("L", SIZE, 128)
    result = Image.composite(depth, neutral, person)

    out = BytesIO()
    result.save(out, format="PNG", optimize=True)
    return out.getvalue()
