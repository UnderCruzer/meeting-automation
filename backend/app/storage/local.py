import json
import uuid
from pathlib import Path

import aiofiles


_COPY_CHUNK = 1024 * 1024


class AudioSizeError(ValueError):
    def __init__(self, message: str, too_large: bool) -> None:
        super().__init__(message)
        self.too_large = too_large


class LocalStorage:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save_audio_stream(self, upload, meeting_id: str, max_bytes: int, min_bytes: int = 44) -> str:
        """Copy an UploadFile to disk in chunks (never holding it in memory); return the file key.

        Raises AudioSizeError and removes the partial file when the size is out of range.
        """
        safe_id = _safe_name(meeting_id)
        dir_path = self.base_dir / safe_id
        dir_path.mkdir(parents=True, exist_ok=True)
        file_key = f"{safe_id}/{uuid.uuid4().hex}.wav"
        path = self.base_dir / file_key

        written = 0
        try:
            async with aiofiles.open(path, "wb") as f:
                while chunk := await upload.read(_COPY_CHUNK):
                    written += len(chunk)
                    if written > max_bytes:
                        raise AudioSizeError(f"Audio file exceeds {max_bytes // (1024 * 1024)} MB limit", True)
                    await f.write(chunk)
            if written < min_bytes:
                raise AudioSizeError("Audio file too small to be valid WAV", False)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return file_key

    async def save_metadata(self, file_key: str, metadata: dict) -> None:
        """Write metadata JSON alongside the audio file."""
        meta_path = self.base_dir / (file_key[:-4] + ".json")
        async with aiofiles.open(meta_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(metadata, ensure_ascii=False, indent=2))


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
