"""叙事分段：NPC 台词不独立外发，由 GM 统一编排后用标记表达说话人。"""
import re
from dataclasses import dataclass

MARKER_RE = re.compile(r"\[\[npc:([A-Za-z0-9_\-]+)\]\]\s*(.*?)\s*\[\[/npc\]\]", re.S)


@dataclass(frozen=True)
class Segment:
    speaker: str  # "gm" 或 f"npc:{npc_id}"
    text: str


def parse_segments(text: str) -> list[Segment]:
    segments: list[Segment] = []
    pos = 0
    for m in MARKER_RE.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            segments.append(Segment("gm", before))
        segments.append(Segment(f"npc:{m.group(1)}", m.group(2).strip()))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        segments.append(Segment("gm", tail))
    if not segments and text.strip():
        segments.append(Segment("gm", text.strip()))
    return segments
