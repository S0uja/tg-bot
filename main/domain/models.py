from dataclasses import dataclass

from main.domain.enums import GenerationKind, GenerationStatus


@dataclass(slots=True)
class Character:
    id: int
    user_id: int
    name: str
    face_file_id: str | None
    description: str
    created_at: str
    updated_at: str | None = None
    body_reference_file_id: str | None = None
    weight: float | None = None
    bust: float | None = None
    age: int | None = None
    weight_profile: str | None = None
    body_shape: str | None = None
    bust_size: int | None = None
    bust_shape: str | None = None
    age_category: str | None = None
    hairstyle: str | None = None
    hair_color: str | None = None
    consistency_strength: str | None = "medium"


@dataclass(slots=True)
class Generation:
    id: int
    user_id: int
    character_id: int | None
    kind: GenerationKind
    prompt: str
    pose: str | None
    clothing: str | None
    status: GenerationStatus
    result_path: str | None
    provider: str | None
    provider_job_id: str | None
    enhanced_prompt: str | None
    error: str | None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    favorite: int = 0


@dataclass(slots=True)
class ImagePromptContext:
    character_description: str
    scene: str
    pose: str = ""
    clothing: str = ""
    weight_profile: str | None = None
    body_shape: str | None = None
    bust_size: int | None = None
    bust_shape: str | None = None
    age_category: str | None = None
    hairstyle: str | None = None
    hair_color: str | None = None
    consistency_strength: str | None = "medium"
    pose_orientation: str = ""


@dataclass(slots=True)
class GeneratedPrompt:
    positive: str
    negative: str = ""
