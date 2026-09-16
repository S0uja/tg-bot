from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    bot_token: str
    database_path: str = "data/bot.sqlite3"
    media_path: str = "data/media"


    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_llm_workflow_create: str = "main/workflows/qwen_prompt_create_api.json"
    comfyui_llm_workflow_vision: str = "main/workflows/qwen_prompt_vision_api.json"
    comfyui_llm_model_match: str = "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    comfyui_llm_timeout: int = 600
    comfyui_llm_poll_interval: float = 0.5
    comfyui_input_path: str = r"C:\AI\ComfyUI_windows_portable\ComfyUI\input"
    comfyui_image_generate_workflow: str = "images/workflows/image_generate_api.json"
    comfyui_image_reface_workflow: str = "images/workflows/image_reface_api.json"
    comfyui_reference_sheet_workflow: str = "images/workflows/reference_sheet_api.json"
    comfyui_video_start_frame_workflow: str = "videos/workflows/video_start_frame_generate_api.json"
    comfyui_controlnet_openpose_model: str = "control_v11p_sd15_openpose.pth"
    comfyui_controlnet_depth_model: str = "control_v11f1p_sd15_depth.pth"
    comfyui_poses_path: str = "poses"
    comfyui_reactor_input_faces_index: str = "0,1,2,3,4,5,6,7"
    comfyui_video_create_workflow: str = "videos/workflows/ltxvideo-i2v-motion-create-video.json"
    comfyui_video_animate_workflow: str = "videos/workflows/ltxvideo-i2v-motion-animate-image.json"
    comfyui_video_decode_workflow: str = "videos/workflows/video_decode_tiled_api.json"
    comfyui_video_decode_fallback_workflow: str = "videos/workflows/video_decode_tiled_api.json"
    comfyui_video_reface_workflow: str = "videos/workflows/video_reface_api.json"
    # LTXV 0.9.x uses a T5 XXL text encoder; this is NOT the video checkpoint.
    comfyui_video_text_encoder: str = "t5xxl_fp8_e4m3fn.safetensors"
    comfyui_timeout: int = 300
    comfyui_poll_interval: float = 1.0
    comfyui_log_workflow: bool = True
    test_poses_enabled: bool = False

    # Feature switches. Each feature lives in its own top-level module folder.
    # Set to false in .env to disable its Telegram handlers and UI.
    feature_characters_enabled: bool = True
    feature_chat_enabled: bool = True
    feature_images_enabled: bool = True
    feature_videos_enabled: bool = True
    feature_poses_enabled: bool = True
    feature_library_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
Path(settings.media_path).mkdir(parents=True, exist_ok=True)
