import asyncio
import io
import wave
from unittest.mock import AsyncMock

from app.services import stt
from app.models.transcript import TranscriptSegment

RATE = 16_000


def _wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x00\x00" * int(seconds * RATE))
    return buf.getvalue()


def _frames(chunk: bytes) -> int:
    with wave.open(io.BytesIO(chunk), "rb") as w:
        return w.getnframes()


def test_small_file_is_single_chunk():
    data = _wav(2)
    assert stt._split_wav(data) == [(0.0, data)]


def test_non_wav_over_limit_is_passed_through():
    data = b"not a wav" * 100
    assert stt._split_wav(data, max_bytes=10) == [(0.0, data)]


def test_split_respects_byte_limit_and_offsets(monkeypatch):
    monkeypatch.setenv("STT_CHUNK_SECONDS", "600")
    data = _wav(5)
    limit = 2 * RATE * 2 + 44  # 2 seconds per chunk
    chunks = stt._split_wav(data, max_bytes=limit)
    assert [offset for offset, _ in chunks] == [0.0, 2.0, 4.0]
    assert all(len(c) <= limit for _, c in chunks)
    assert sum(_frames(c) for _, c in chunks) == 5 * RATE


def test_chunk_seconds_env_used_when_smaller_than_limit(monkeypatch):
    monkeypatch.setenv("STT_CHUNK_SECONDS", "1")
    chunks = stt._split_wav(_wav(3), max_bytes=2 * RATE * 2 + 44)
    assert [offset for offset, _ in chunks] == [0.0, 1.0, 2.0]


def test_transcribe_api_merges_chunks_with_offsets(tmp_path, monkeypatch):
    monkeypatch.setenv("STT_CHUNK_SECONDS", "2")
    monkeypatch.setattr(stt, "_API_MAX_BYTES", 2 * RATE * 2 + 44)
    path = tmp_path / "a.wav"
    path.write_bytes(_wav(4))
    fake = AsyncMock(side_effect=[
        ([TranscriptSegment(start=0.5, end=1.5, text="첫 청크")], "ko", 2.0, "groq-whisper"),
        ([TranscriptSegment(start=0.2, end=1.8, text="둘째 청크")], "ko", 2.0, "groq-whisper"),
    ])
    monkeypatch.setattr(stt, "_transcribe_chunk", fake)

    result = asyncio.run(stt._transcribe_api(path, "m1"))

    assert fake.await_count == 2
    assert [(s.start, s.end) for s in result.segments] == [(0.5, 1.5), (2.2, 3.8)]
    assert result.full_text == "첫 청크 둘째 청크"
    assert result.duration == 4.0
    assert result.language == "ko"
    assert result.backend == "groq-whisper"
