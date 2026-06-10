"""Unit tests for PII detection and masking (guard.py)."""
import pytest
from app.services.guard import detect_and_mask, mask_transcript_segments


class TestDetectAndMask:
    def test_rrn_masked(self):
        result = detect_and_mask("주민번호는 901225-1234567입니다.")
        assert "[MASKED_RRN]" in result.masked_text
        assert "901225-1234567" not in result.masked_text
        assert result.has_pii

    def test_card_number_masked(self):
        result = detect_and_mask("카드번호 1234-5678-9012-3456 결제해주세요.")
        assert "[MASKED_CARD]" in result.masked_text
        assert "1234-5678-9012-3456" not in result.masked_text

    def test_phone_kr_masked(self):
        result = detect_and_mask("연락처는 010-1234-5678입니다.")
        assert "[MASKED_PHONE_KR]" in result.masked_text
        assert "010-1234-5678" not in result.masked_text

    def test_email_masked(self):
        result = detect_and_mask("이메일은 user@example.com으로 보내주세요.")
        assert "[MASKED_EMAIL]" in result.masked_text
        assert "user@example.com" not in result.masked_text

    def test_password_hint_masked(self):
        result = detect_and_mask("비밀번호: P@ssw0rd123 입력하세요.")
        assert "[MASKED_PASSWORD_HINT]" in result.masked_text
        assert "P@ssw0rd123" not in result.masked_text

    def test_no_pii_returns_original(self):
        text = "오늘 회의에서 프로젝트 일정을 논의했습니다."
        result = detect_and_mask(text)
        assert result.masked_text == text
        assert not result.has_pii
        assert result.matches == []

    def test_multiple_pii_all_masked(self):
        text = "전화 010-9876-5432, 이메일 admin@corp.com"
        result = detect_and_mask(text)
        assert "010-9876-5432" not in result.masked_text
        assert "admin@corp.com" not in result.masked_text
        assert len(result.matches) == 2

    def test_overlapping_patterns_resolved(self):
        # Should not crash or produce garbled text with overlapping matches
        text = "비밀번호: abc@def.com"  # email inside password hint context
        result = detect_and_mask(text)
        assert result.masked_text  # non-empty
        assert "abc@def.com" not in result.masked_text

    def test_empty_string(self):
        result = detect_and_mask("")
        assert result.masked_text == ""
        assert not result.has_pii

    def test_match_positions_recorded(self):
        result = detect_and_mask("번호: 010-1111-2222")
        assert len(result.matches) == 1
        m = result.matches[0]
        assert m.type == "PHONE_KR"
        assert m.original == "010-1111-2222"


class TestMaskTranscriptSegments:
    def test_masks_segment_text(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "전화번호는 010-1234-5678"},
            {"start": 1.0, "end": 2.0, "text": "일반 텍스트"},
        ]
        masked, matches = mask_transcript_segments(segments)
        assert "010-1234-5678" not in masked[0]["text"]
        assert "[MASKED_PHONE_KR]" in masked[0]["text"]
        assert masked[1]["text"] == "일반 텍스트"
        assert len(matches) == 1

    def test_preserves_non_text_fields(self):
        segments = [{"start": 0.5, "end": 1.5, "text": "user@test.com", "speaker": "A"}]
        masked, _ = mask_transcript_segments(segments)
        assert masked[0]["start"] == 0.5
        assert masked[0]["speaker"] == "A"

    def test_empty_segments(self):
        masked, matches = mask_transcript_segments([])
        assert masked == []
        assert matches == []
