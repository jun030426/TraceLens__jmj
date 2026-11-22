"""Bind the student's submitted source to the template used by the editor."""
from pydantic import BaseModel, ConfigDict, Field

from lerny.security import deny

BLANK = "[[빈칸]]"


class SubmissionEditor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str = Field(max_length=100_000)
    fills: list[str] | None = Field(default=None, max_length=1000)


def _legacy_fills(template, source):
    """Old clients provide only source. A single blank per line has unambiguous bounds."""
    lines, submitted = template.split("\n"), source.split("\n")
    if len(lines) != len(submitted):
        return None
    fills = []
    for line, actual in zip(lines, submitted):
        left, token, right = line.partition(BLANK)
        if not token:
            if line != actual:
                return None
            continue
        end = len(actual) - len(right)
        if BLANK in right or not actual.startswith(left) or not actual.endswith(right) or end <= len(left):
            return None
        fills.append(actual[len(left):end])
    return fills


def submission_snapshot(kind, template, source, editor):
    if editor is not None and editor.template != template:
        deny(409, "문제의 시작 코드가 변경됐어요. 새로고침한 뒤 확인해 주세요.")
    if kind == "full":
        return {"kind": "full", "starter_code": template}

    fills = _legacy_fills(template, source) if editor is None else editor.fills
    parts = template.split(BLANK)
    if not fills or len(parts) != len(fills) + 1 or any(not v.strip() or "\n" in v or "\r" in v for v in fills):
        if editor is None:
            return None
        deny(422, "제출한 빈칸 정보를 확인해 주세요.")
    spans = []
    offset = 0
    fragments = []
    for number, (literal, value) in enumerate(zip(parts[:-1], fills, strict=True), 1):
        fragments.extend((literal, value))
        # JS String.slice uses UTF-16 code units and an exclusive end, even after emoji.
        start = offset + len(literal.encode("utf-16-le")) // 2
        offset = start + len(value.encode("utf-16-le")) // 2
        spans.append({"number": number, "start": start, "end": offset})
    if "".join(fragments) + parts[-1] != source:
        deny(422, "제출 코드와 빈칸 내용이 일치하지 않아요.")
    return {"kind": "blank", "spans": spans}
