from pathlib import Path
from typing import Protocol


class MediaStorage(Protocol):
    async def save(self, data: bytes, filename: str) -> str: ...
    async def read(self, path: str) -> bytes: ...


class LocalMediaStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    async def save(self, data: bytes, filename: str) -> str:
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    async def read(self, path: str) -> bytes:
        return Path(path).read_bytes()
