from typing import Protocol

from main.domain.models import Character


class ImageGenerator(Protocol):
    async def generate(
        self,
        *,
        character: Character,
        prompt: str,
        reference_image: bytes | None,
        workflow_path: str | None = None,
        reactor_input_faces_index: str | None = None,
        body_reference_image: bytes | None = None,
        pose_image: bytes | None = None,
        pose_visual_reference_image: bytes | None = None,
        depth_image: bytes | None = None,
    ) -> bytes: ...

    async def reface(self, *, image: bytes, face_reference: bytes, reactor_input_faces_index: str | None = None) -> bytes: ...
