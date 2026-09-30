import asyncio
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import upload
from app.services import stt
from app.services.workspace import Workspace
from app.storage.local import AudioSizeError, LocalStorage


class _FakeUpload:
    """Minimal UploadFile stand-in that records the largest single read."""

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)
        self.max_read = 0

    async def read(self, size: int = -1) -> bytes:
        chunk = self._buf.read(size)
        self.max_read = max(self.max_read, len(chunk))
        return chunk


def _wav(seconds: float, rate: int = 16_000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def test_stream_save_copies_in_bounded_chunks(tmp_path):
    storage = LocalStorage(tmp_path)
    data = _wav(90)  # ~2.9 MB
    fake = _FakeUpload(data)
    key = asyncio.run(storage.save_audio_stream(fake, "m/1", max_bytes=10 * 1024 * 1024))
    assert (tmp_path / key).read_bytes() == data
    assert key.startswith("m_1/") and key.endswith(".wav")
    assert fake.max_read <= 1024 * 1024


@pytest.mark.parametrize("data,max_bytes,too_large", [(b"x" * 5000, 4096, True), (b"x" * 10, 4096, False)])
def test_stream_save_rejects_and_removes_partial_file(tmp_path, data, max_bytes, too_large):
    storage = LocalStorage(tmp_path)
    with pytest.raises(AudioSizeError) as exc:
        asyncio.run(storage.save_audio_stream(_FakeUpload(data), "m", max_bytes=max_bytes))
    assert exc.value.too_large is too_large
    assert not list((tmp_path / "m").iterdir())


def _app(tmp_path, monkeypatch, max_bytes):
    monkeypatch.setattr(upload, "MAX_FILE_BYTES", max_bytes)
    monkeypatch.setattr(upload, "_run_stt_and_guard", lambda *a, **k: None)
    app = FastAPI()
    app.state.storage = LocalStorage(tmp_path)
    app.state.workspace = Workspace(tmp_path)
    app.include_router(upload.router)
    return TestClient(app)


_META = json.dumps({"meetingId": "m", "title": "t", "startTime": "2026-01-01T00:00:00Z", "endTime": "2026-01-01T01:00:00Z"})


def test_upload_endpoint_status_codes(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, max_bytes=100_000)
    ok = client.post("/upload", files={"audio": ("a.wav", _wav(1), "audio/wav")}, data={"metadata": _META})
    assert ok.status_code == 200
    assert (tmp_path / ok.json()["fileKey"]).exists()
    big = client.post("/upload", files={"audio": ("a.wav", _wav(5), "audio/wav")}, data={"metadata": _META})
    assert big.status_code == 413
    small = client.post("/upload", files={"audio": ("a.wav", b"RIFF", "audio/wav")}, data={"metadata": _META})
    assert small.status_code == 422
    # Only the accepted upload remains on disk.
    assert len(list((tmp_path / "m").glob("*.wav"))) == 1


def test_wav_chunks_are_produced_lazily():
    data = _wav(5)
    chunks = stt._iter_wav_chunks(io.BytesIO(data), len(data), max_bytes=2 * 16_000 * 2 + 44)
    first = next(chunks)
    assert first[0] == 0.0
    assert [o for o, _ in chunks] == [2.0, 4.0]
