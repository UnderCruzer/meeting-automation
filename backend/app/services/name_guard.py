from __future__ import annotations
"""
Name pseudonymisation — replace person names with [PERSON_n] before any LLM call.

Sources of names:
- participant names entered at upload (most reliable)
- Korean "surname + given name + honorific/title" (김민수 팀장, 박지은님)
- English "Mr./Ms./Mrs./Dr. Name"

The same name maps to the same token across the whole meeting. The mapping stays
on our server; `unmask` restores names in results shown to signed-in users.
"""
import json
import re
from dataclasses import dataclass, field
from pydantic import BaseModel

# Two-syllable surnames first so the alternation prefers them.
_SURNAMES = (
    "남궁|황보|제갈|선우|독고|사공|서문|"
    "김|이|박|최|정|강|조|윤|장|임|한|오|서|신|권|황|안|송|류|유|전|홍|고|문|양|손|배|백|허|남|심|노|하|곽|성|차|주|우|구|"
    "민|진|나|지|엄|채|원|천|방|공|현|함|변|염|여|추|도|소|석|선|설|마|길|연|위|표|명|기|반|왕|금|옥|육|인|맹|제|모|탁|국|어|은|편|용|예|봉|경|사|부"
)
_TITLES = (
    "님|씨|팀장|과장|부장|차장|대리|사원|주임|매니저|프로|책임|선임|수석|이사|상무|전무|"
    "대표|사장|실장|본부장|센터장|교수|박사|선생님|선생|연구원|파트장|그룹장|리더"
)
_KO_NAME = re.compile(
    rf"(?<![가-힣])((?:{_SURNAMES})[가-힣]{{1,2}})(?=\s?(?:{_TITLES}))"
)
_EN_NAME = re.compile(r"\b(?:Mr|Ms|Mrs|Dr)\.?\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")
# Words that look like "surname + syllable" before a title but are not names.
_NOT_NAMES = {"고객", "이번", "정부", "주요", "전체", "우리", "모든", "각자", "기존", "신규", "해당", "담당", "부서"}
_TOKEN = re.compile(r"\[?PERSON_(\d+)\]?")


@dataclass
class NameMap:
    names: dict[str, str] = field(default_factory=dict)  # name -> token

    def token(self, name: str) -> str:
        if name not in self.names:
            self.names[name] = f"[PERSON_{len(self.names) + 1}]"
        return self.names[name]

    def as_dict(self) -> dict[str, str]:
        """token -> name, the shape used for unmasking."""
        return {token: name for name, token in self.names.items()}


def _collect(texts: list[str], participants: list[str]) -> NameMap:
    found: list[str] = [p.strip() for p in participants if len(p.strip()) >= 2]
    for text in texts:
        for m in _KO_NAME.finditer(text):
            name = m.group(1)
            if name not in _NOT_NAMES:
                found.append(name)
        found.extend(m.group(1) for m in _EN_NAME.finditer(text))
    mapping = NameMap()
    for name in found:
        mapping.token(name)
    return mapping


def _replacement_pattern(mapping: NameMap) -> tuple[re.Pattern, dict[str, str]] | None:
    variants: dict[str, str] = {}
    for name, token in mapping.names.items():
        variants[name] = token
        # Korean full name → also replace the given name when used with 님/씨 ("민수님").
        if re.fullmatch(r"[가-힣]{3,4}", name):
            variants[name[1:] + "님"] = token + "님"
            variants[name[1:] + "씨"] = token + "씨"
    if not variants:
        return None
    alternation = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<![가-힣A-Za-z])(?:{alternation})"), variants


def pseudonymise_segments(
    segments: list[dict], participants: list[str] | None = None
) -> tuple[list[dict], dict[str, str]]:
    """Replace names in every segment's text. Returns (segments, token -> name)."""
    mapping = _collect([s.get("text", "") for s in segments], participants or [])
    compiled = _replacement_pattern(mapping)
    if compiled is None:
        return segments, {}
    pattern, variants = compiled
    out = [{**s, "text": pattern.sub(lambda m: variants[m.group(0)], s.get("text", ""))} for s in segments]
    return out, mapping.as_dict()


def unmask_text(text: str, tokens: dict[str, str]) -> str:
    if not tokens:
        return text
    return _TOKEN.sub(lambda m: tokens.get(f"[PERSON_{m.group(1)}]", m.group(0)), text)


def unmask_model(model: BaseModel, tokens: dict[str, str]) -> BaseModel:
    """Return a copy of `model` with PERSON tokens restored in every string field."""
    if not tokens:
        return model
    restored = unmask_text(json.dumps(model.model_dump(), ensure_ascii=False), tokens)
    return type(model).model_validate(json.loads(restored))
