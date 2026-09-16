from enum import StrEnum


class GenerationKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class GenerationStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
