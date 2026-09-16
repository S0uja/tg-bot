from videos.provider.comfyui import _image_dimensions, _video_dimensions_for_source


def _png(width: int, height: int) -> bytes:
    import struct
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"


def test_v35_detects_png_dimensions():
    assert _image_dimensions(_png(512, 768)) == (512, 768)


def test_v35_preserves_portrait_orientation():
    assert _video_dimensions_for_source(_png(512, 768)) == (512, 768)


def test_v35_preserves_landscape_orientation():
    assert _video_dimensions_for_source(_png(768, 512)) == (768, 512)


def test_v35_uses_square_for_square_source():
    assert _video_dimensions_for_source(_png(512, 512)) == (512, 512)
