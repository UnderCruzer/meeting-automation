"""
PDF Report Generator — builds a formatted meeting minutes PDF from OrchestratorOutput.

Uses fpdf2. Supports KR/EN language selection based on routing region.
Output is written to data/recordings/<meeting_id>/report.pdf.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from app.models.analysis import OrchestratorOutput

logger = logging.getLogger(__name__)

_PRIORITY_EMOJI = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}


class _MeetingPDF(FPDF):
    """FPDF subclass with header/footer and helper methods."""

    def __init__(self, title: str, lang: str = "en"):
        super().__init__()
        self._title = title
        self._lang = lang
        self.set_auto_page_break(auto=True, margin=20)
        self.add_page()

    def header(self) -> None:
        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(30, 30, 60)
        self.set_text_color(255, 255, 255)
        self.cell(0, 10, _safe_latin(self._title[:90]), align="L", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-13)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 6, f"Page {self.page_no()} | AI Meeting Automation", align="C")

    def section(self, text: str) -> None:
        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(230, 235, 255)
        self.set_text_color(20, 20, 80)
        self.cell(0, 8, text, fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def body_line(self, text: str, indent: int = 4) -> None:
        self.set_font("Helvetica", size=10)
        self.set_x(self.l_margin + indent)
        # fpdf2 does not support CJK without a CJK font; replace non-latin safely
        safe = _safe_latin(text)
        self.multi_cell(0, 6, safe, new_x="LMARGIN", new_y="NEXT")

    def meta_line(self, label: str, value: str) -> None:
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(80, 80, 80)
        self.cell(30, 6, label)
        self.set_font("Helvetica", size=9)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 6, _safe_latin(value), new_x="LMARGIN", new_y="NEXT")


def _safe_latin(text: str) -> str:
    """Replace characters outside latin-1 with '?' so fpdf2 won't crash.

    fpdf2 core fonts are latin-1 only. A CJK-capable font would require
    embedding a TTF (e.g. NanumGothic), which adds ~3 MB per PDF.
    The trade-off: keep the dependency light; callers targeting Korean
    audiences should embed a TTF and remove this filter.
    """
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build_pdf(output: OrchestratorOutput, lang: str = "en") -> bytes:
    """Render a meeting-minutes PDF and return raw bytes.

    Args:
        output: Structured analysis result from the AI orchestrator.
        lang:   "ko" or "en" — controls section label language.
                Note: KR characters require a CJK TTF font; labels are ASCII.

    Returns:
        PDF content as bytes.
    """
    labels = _labels(lang)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = f"Meeting Report - {output.meeting_id}"

    pdf = _MeetingPDF(title=title, lang=lang)

    # ── Metadata ─────────────────────────────────────────────────────────
    pdf.section(labels["meta"])
    pdf.meta_line(labels["meeting_id"], output.meeting_id)
    pdf.meta_line(labels["generated"], now)
    conf_pct = f"{int(output.confidence * 100)}%"
    pdf.meta_line(labels["confidence"], conf_pct)
    if output.participants_mentioned:
        pdf.meta_line(labels["participants"], ", ".join(output.participants_mentioned))
    pdf.ln(3)

    # ── Summary ──────────────────────────────────────────────────────────
    pdf.section(labels["summary"])
    summary = output.summary_ko if lang == "ko" else output.summary_en
    pdf.body_line(summary, indent=0)
    pdf.ln(3)

    # ── Topics ───────────────────────────────────────────────────────────
    if output.topics:
        pdf.section(labels["topics"])
        for i, topic in enumerate(output.topics, 1):
            pdf.body_line(f"{i}. {topic}")
        pdf.ln(3)

    # ── Decisions ────────────────────────────────────────────────────────
    if output.decisions:
        pdf.section(labels["decisions"])
        for decision in output.decisions:
            pdf.body_line(f"- {decision}")
        pdf.ln(3)

    # ── Action Items ─────────────────────────────────────────────────────
    if output.action_items:
        pdf.section(labels["action_items"])
        for item in output.action_items:
            priority_tag = _PRIORITY_EMOJI.get(item.priority, "")
            assignee = f" [{item.assignee}]" if item.assignee else ""
            due = f" (due: {item.due_date})" if item.due_date else ""
            pdf.body_line(f"{priority_tag} {item.description}{assignee}{due}")
        pdf.ln(3)

    # ── Quality / Routing note ───────────────────────────────────────────
    pdf.section(labels["routing"])
    routing_str = ", ".join(output.routing) if output.routing else "none"
    pdf.body_line(f"{labels['routing_label']}: {routing_str}")
    pdf.ln(2)

    return bytes(pdf.output())


def save_pdf(output: OrchestratorOutput, base_dir: Path, lang: str = "en") -> Path:
    """Generate PDF and persist to <base_dir>/<meeting_id>/report.pdf.

    Returns the path to the saved file.
    """
    dest = base_dir / output.meeting_id / "report.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = build_pdf(output, lang=lang)
    dest.write_bytes(content)
    logger.info("[PDFReport] Saved %d bytes → %s", len(content), dest)
    return dest


def _labels(lang: str) -> dict[str, str]:
    if lang == "ko":
        return {
            "meta": "Meeting Information",
            "meeting_id": "ID",
            "generated": "Generated",
            "confidence": "AI Confidence",
            "participants": "Participants",
            "summary": "Summary (KO)",
            "topics": "Key Topics",
            "decisions": "Decisions",
            "action_items": "Action Items",
            "routing": "Routing",
            "routing_label": "Artifacts",
        }
    return {
        "meta": "Meeting Information",
        "meeting_id": "ID",
        "generated": "Generated",
        "confidence": "AI Confidence",
        "participants": "Participants",
        "summary": "Summary",
        "topics": "Key Topics",
        "decisions": "Decisions",
        "action_items": "Action Items",
        "routing": "Routing",
        "routing_label": "Artifacts",
    }
