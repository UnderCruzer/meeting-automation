"""Unit tests for pdf_report service."""
import pytest
from pathlib import Path

from app.models.analysis import ActionItem, OrchestratorOutput
from app.services.pdf_report import build_pdf, save_pdf, _safe_latin, _labels


def _sample_output(**kwargs) -> OrchestratorOutput:
    defaults = dict(
        meeting_id="test-meeting-001",
        topics=["Sprint planning", "Budget review"],
        decisions=["Adopt new CI pipeline", "Freeze scope until Q3"],
        action_items=[
            ActionItem(description="Set up GitHub Actions", assignee="Alice", due_date="2026-06-20", priority="high"),
            ActionItem(description="Write ADR for auth service", assignee="Bob", priority="medium"),
            ActionItem(description="Update README", priority="low"),
        ],
        participants_mentioned=["Alice", "Bob", "Carol"],
        summary_ko="스프린트 계획 및 예산 검토 회의가 진행되었습니다.",
        summary_en="Sprint planning and budget review meeting was held.",
        confidence=0.92,
        routing=["jira", "slack"],
    )
    defaults.update(kwargs)
    return OrchestratorOutput(**defaults)


class TestBuildPdf:
    def test_returns_bytes(self):
        result = build_pdf(_sample_output())
        assert isinstance(result, bytes)

    def test_pdf_header_magic_bytes(self):
        result = build_pdf(_sample_output())
        assert result[:4] == b"%PDF"

    def test_non_zero_size(self):
        result = build_pdf(_sample_output())
        assert len(result) > 1024

    def test_en_lang_produces_pdf(self):
        result = build_pdf(_sample_output(), lang="en")
        assert result[:4] == b"%PDF"

    def test_ko_lang_produces_pdf(self):
        result = build_pdf(_sample_output(), lang="ko")
        assert result[:4] == b"%PDF"

    def test_empty_topics_no_crash(self):
        result = build_pdf(_sample_output(topics=[]))
        assert result[:4] == b"%PDF"

    def test_empty_decisions_no_crash(self):
        result = build_pdf(_sample_output(decisions=[]))
        assert result[:4] == b"%PDF"

    def test_empty_action_items_no_crash(self):
        result = build_pdf(_sample_output(action_items=[]))
        assert result[:4] == b"%PDF"

    def test_no_participants_no_crash(self):
        result = build_pdf(_sample_output(participants_mentioned=[]))
        assert result[:4] == b"%PDF"

    def test_zero_confidence_no_crash(self):
        result = build_pdf(_sample_output(confidence=0.0))
        assert result[:4] == b"%PDF"

    def test_long_summary_no_crash(self):
        long_summary = "This is a very long summary. " * 50
        result = build_pdf(_sample_output(summary_en=long_summary))
        assert result[:4] == b"%PDF"

    def test_action_item_all_priorities(self):
        items = [
            ActionItem(description="High task", priority="high"),
            ActionItem(description="Med task", priority="medium"),
            ActionItem(description="Low task", priority="low"),
        ]
        result = build_pdf(_sample_output(action_items=items))
        assert result[:4] == b"%PDF"


class TestSavePdf:
    def test_file_created(self, tmp_path):
        output = _sample_output()
        path = save_pdf(output, base_dir=tmp_path)
        assert path.exists()
        assert path.suffix == ".pdf"

    def test_file_under_meeting_subdir(self, tmp_path):
        output = _sample_output(meeting_id="mtg-42")
        path = save_pdf(output, base_dir=tmp_path)
        assert path.parent.name == "mtg-42"

    def test_file_named_report(self, tmp_path):
        output = _sample_output()
        path = save_pdf(output, base_dir=tmp_path)
        assert path.name == "report.pdf"

    def test_file_content_is_pdf(self, tmp_path):
        output = _sample_output()
        path = save_pdf(output, base_dir=tmp_path)
        assert path.read_bytes()[:4] == b"%PDF"

    def test_creates_parent_dirs(self, tmp_path):
        output = _sample_output(meeting_id="deep/nested/mtg")
        path = save_pdf(output, base_dir=tmp_path)
        assert path.exists()

    def test_ko_lang_saves(self, tmp_path):
        output = _sample_output()
        path = save_pdf(output, base_dir=tmp_path, lang="ko")
        assert path.exists()


class TestSafeLatin:
    def test_ascii_unchanged(self):
        assert _safe_latin("Hello World") == "Hello World"

    def test_cjk_replaced(self):
        result = _safe_latin("안녕하세요")
        assert "?" in result

    def test_latin1_extended_unchanged(self):
        assert _safe_latin("café résumé") == "café résumé"

    def test_empty_string(self):
        assert _safe_latin("") == ""


class TestLabels:
    def test_en_labels_returned(self):
        lbls = _labels("en")
        assert lbls["summary"] == "Summary"

    def test_ko_labels_returned(self):
        lbls = _labels("ko")
        assert "KO" in lbls["summary"]

    def test_unknown_lang_defaults_en(self):
        lbls = _labels("fr")
        assert lbls["summary"] == "Summary"
