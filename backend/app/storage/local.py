import json
import uuid
from pathlib import Path

import aiofiles


class LocalStorage:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save_audio(self, data: bytes, meeting_id: str) -> str:
        """Persist audio bytes and return the relative file key."""
        safe_id = _safe_name(meeting_id)
        job_id = uuid.uuid4().hex
        dir_path = self.base_dir / safe_id
        dir_path.mkdir(parents=True, exist_ok=True)

        file_key = f"{safe_id}/{job_id}.wav"
        async with aiofiles.open(self.base_dir / file_key, "wb") as f:
            await f.write(data)
        return file_key

    async def save_metadata(self, file_key: str, metadata: dict) -> None:
        """Write metadata JSON alongside the audio file."""
        meta_path = self.base_dir / file_key.replace(".wav", ".json")
        async with aiofiles.open(meta_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(metadata, ensure_ascii=False, indent=2))


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
