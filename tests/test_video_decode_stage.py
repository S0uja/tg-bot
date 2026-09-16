import json
from pathlib import Path


def test_ltxv_stage_saves_latent_instead_of_decoding_video():
    wf = json.loads(Path('videos/workflows/ltxvideo-i2v-motion-create-video.json').read_text(encoding='utf-8'))
    assert wf['110']['class_type'] == 'SaveLatent'
    assert wf['110']['inputs']['samples'] == ['101', 1]
    assert '8' not in wf
    assert '103' not in wf


def test_tiled_decode_is_the_configured_decode_workflow():
    wf = json.loads(Path('videos/workflows/video_decode_tiled_api.json').read_text(encoding='utf-8'))
    assert wf['3']['class_type'] == 'VAEDecodeTiled'
    assert wf['3']['inputs']['tile_size'] == 512
    assert wf['3']['inputs']['overlap'] == 64


def test_config_uses_current_decode_workflow():
    text = Path('main/config.py').read_text(encoding='utf-8')
    assert 'comfyui_video_decode_workflow: str = "videos/workflows/video_decode_tiled_api.json"' in text
    assert 'comfyui_video_decode_fallback_workflow: str = "videos/workflows/video_decode_tiled_api.json"' in text


def test_provider_frees_memory_between_ltxv_and_decode():
    text = Path('main/infrastructure/ai/video/comfyui.py').read_text(encoding='utf-8')
    assert 'await self._free_comfy_memory(session)' in text
    assert 'self._decode_latent_to_video' in text


def test_main_uses_two_stage_provider_for_ltxv_and_reface():
    text = Path('main/main.py').read_text(encoding='utf-8')
    assert 'decode_workflow_path=settings.comfyui_video_decode_workflow' in text
    assert 'video_reface_provider = ltxv_video_provider' in text
    assert 'LegacyLTXVVideoGenerator' not in text
