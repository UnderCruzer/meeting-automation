"""
Ingestion Guard — PII detection and masking for transcript text.

Phase 1: regex-based patterns for common Korean/global PII.
Each pattern is compiled once at module load; masking replaces with [MASKED_<TYPE>].

Patterns covered:
- 주민등록번호 (Korean RRN): NNNNNN-NNNNNNN
- 카드번호 (credit card): 16-digit groups
- 전화번호 (Korean phone): 01X-XXXX-XXXX
- 이메일 (email)
- 비밀번호 hints (password keyword + alphanumeric string)
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import aiofiles

logger = logging.getLogger(__name__)


@dataclass
class PiiMatch:
    type: str
    start: int
    end: int
    original: str


@dataclass
class GuardResult:
    original_text: str
    masked_text: str
    matches: list[PiiMatch] = field(default_factory=list)

    @property
    def has_pii(self) -> bool:
        return len(self.matches) > 0


_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("RRN", re.compile(r"\b\d{6}-[1-4]\d{6}\b")),
    ("CARD", re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b")),
    ("PHONE_KR", re.compile(r"\b01[016789]-\d{3,4}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    (
        "PASSWORD_HINT",
        re.compile(
            r"(?:비밀번호|패스워드|password|pwd)\s*[:=]?\s*([A-Za-z0-9!@#$%^&*]{6,})",
            re.IGNORECASE,
        ),
    ),
]


def detect_and_mask(text: str) -> GuardResult:
    """
    Scan text for PII, return masked copy and list of matches.
    Overlapping matches are resolved by taking the first (leftmost) match.
    """
    matches: list[PiiMatch] = []

    for pii_type, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            # For PASSWORD_HINT use group 1 (the password value) if captured
            if pii_type == "PASSWORD_HINT" and m.lastindex and m.lastindex >= 1:
                start, end = m.start(1), m.end(1)
            else:
                start, end = m.start(), m.end()
            matches.append(PiiMatch(type=pii_type, start=start, end=end, original=text[start:end]))

    # Sort by start position, resolve overlaps (skip if inside a previous match)
    matches.sort(key=lambda x: x.start)
    resolved: list[PiiMatch] = []
    prev_end = -1
    for match in matches:
        if match.start >= prev_end:
            resolved.append(match)
            prev_end = match.end

    # Build masked text right-to-left so indices stay valid
    chars = list(text)
    for match in reversed(resolved):
        chars[match.start:match.end] = list(f"[MASKED_{match.type}]")

    if resolved:
        logger.info("[Guard] Masked %d PII item(s): %s", len(resolved), [m.type for m in resolved])

    return GuardResult(
        original_text=text,
        masked_text="".join(chars),
        matches=resolved,
    )


def mask_transcript_segments(segments: list[dict]) -> tuple[list[dict], list[PiiMatch]]:
    """Apply masking to each segment's text. Returns masked segments and all matches."""
    all_matches: list[PiiMatch] = []
    masked_segments = []
    for seg in segments:
        result = detect_and_mask(seg.get("text", ""))
        masked_segments.append({**seg, "text": result.masked_text})
        all_matches.extend(result.matches)
    return masked_segments, all_matches


async def save_guard_report(
    file_key: str,
    base_dir: Path,
    matches: list[PiiMatch],
    masked_full_text: str,
) -> None:
    """Persist guard report (masked text + match metadata) as JSON sidecar."""
    report = {
        "pii_count": len(matches),
        "pii_types": list({m.type for m in matches}),
        "masked_full_text": masked_full_text,
        "matches": [
            {"type": m.type, "start": m.start, "end": m.end}
            for m in matches
        ],
    }
    report_path = base_dir / file_key.replace(".wav", ".guard.json")
    async with aiofiles.open(report_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(report, ensure_ascii=False, indent=2))
