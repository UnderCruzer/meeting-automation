from app.models.summary import CitedActionItem, MeetingSummary
from app.services.name_guard import pseudonymise_segments, unmask_model, unmask_text


def _texts(segments):
    return [s["text"] for s in segments]


def test_korean_names_with_titles_are_tokenised_consistently():
    segs = [{"text": "김민수 팀장이 보고서를 맡고"}, {"text": "박지은님은 일정 확인. 김민수 팀장 다시 확인"}]
    out, tokens = pseudonymise_segments(segs)
    joined = " ".join(_texts(out))
    assert "김민수" not in joined and "박지은" not in joined
    assert joined.count("[PERSON_1]") == 2
    assert set(tokens.values()) == {"김민수", "박지은"}


def test_given_name_with_honorific_follows_full_name():
    out, _ = pseudonymise_segments([{"text": "이영희 과장 참석"}, {"text": "영희님 의견은요?"}])
    assert _texts(out) == ["[PERSON_1] 과장 참석", "[PERSON_1]님 의견은요?"]


def test_two_syllable_surname_and_participants():
    out, tokens = pseudonymise_segments(
        [{"text": "남궁민 대리와 Sarah Kim, Mr. Johnson 이 논의"}], participants=["Sarah Kim"])
    text = out[0]["text"]
    assert "남궁민" not in text and "Sarah Kim" not in text and "Johnson" not in text
    assert len(tokens) == 3


def test_title_with_particles_and_honorific():
    out, _ = pseudonymise_segments([{"text": "정하늘 팀장님께서 결정"}])
    assert out[0]["text"] == "[PERSON_1] 팀장님께서 결정"


def test_common_words_before_titles_are_not_names():
    segs = [{"text": "고객님 요청으로 이번 주 담당 팀장 회의"}]
    out, tokens = pseudonymise_segments(segs)
    assert tokens == {}
    assert out == segs


def test_names_inside_longer_words_are_not_replaced():
    out, _ = pseudonymise_segments([{"text": "최유진 선임"}, {"text": "최유진선임연구원 아님, 미최유진"}], participants=[])
    assert out[0]["text"] == "[PERSON_1] 선임"
    assert out[1]["text"].endswith("미최유진")


def test_unmask_restores_bracketed_and_bare_tokens():
    tokens = {"[PERSON_1]": "김민수", "[PERSON_2]": "박지은"}
    assert unmask_text("[PERSON_1]이 하고 PERSON_2 검토, [PERSON_9] 미상", tokens) == "김민수이 하고 박지은 검토, [PERSON_9] 미상"
    summary = MeetingSummary(meeting_id="m", summary_ko="[PERSON_1] 발표", summary_en="", decisions=[],
                             action_items=[CitedActionItem(description="자료 준비", assignee="[PERSON_2]")],
                             quality_flags=[], quality_ok=True)
    restored = unmask_model(summary, tokens)
    assert restored.summary_ko == "김민수 발표"
    assert restored.action_items[0].assignee == "박지은"


def test_pipeline_sends_tokens_to_llm_and_shows_names(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from app.models.analysis import OrchestratorOutput
    from app.models.transcript import TranscriptResult, TranscriptSegment
    from app.routers import upload
    from app.services.workspace import Workspace

    job = "0123456789abcdef0123456789abcdef"
    text = "김민수 팀장이 보고서 검토, Sarah 는 일정 확인"
    transcript = TranscriptResult(meetingId="m", language="ko", duration=60, backend="test", full_text=text,
                                  segments=[TranscriptSegment(start=0, end=60, text=text)])

    async def fake_analyse(t, masked_text):
        # The LLM only ever sees tokens and answers with them.
        import re
        assert "김민수" not in masked_text and "Sarah" not in masked_text
        lead = re.search(r"\[PERSON_(\d+)\] 팀장", masked_text).group(1)
        return OrchestratorOutput(meeting_id="m", topics=[], decisions=[],
                                  action_items=[{"description": "보고서 검토", "assignee": f"PERSON_{lead}"}],
                                  participants_mentioned=[], summary_ko=f"[PERSON_{lead}] 보고서 검토",
                                  summary_en="", confidence=.9, routing=[])

    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    monkeypatch.delenv("RETAIN_RAW_RECORDINGS", raising=False)
    monkeypatch.setattr(upload, "transcribe", AsyncMock(return_value=transcript))
    analyse = AsyncMock(side_effect=fake_analyse)
    monkeypatch.setattr(upload, "analyse", analyse)
    for name in ("save_guard_report", "save_analysis", "save_summary"):
        monkeypatch.setattr(upload, name, AsyncMock())
    store = Workspace(tmp_path)
    store.create(job, "회의")
    (tmp_path / "m").mkdir()
    audio = tmp_path / "m" / f"{job}.wav"
    audio.write_bytes(b"RIFF")

    asyncio.run(upload._run_stt_and_guard(audio, f"m/{job}.wav", "m", tmp_path, ["Sarah"]))

    analyse.assert_awaited_once()
    summary = store.list()[0]["summary"]
    assert summary["summary_ko"] == "김민수 보고서 검토"
    assert summary["action_items"][0]["assignee"] == "김민수"
    assert "PERSON" not in str(summary)
    assert (tmp_path / "m" / f"{job}.names.json").exists()
