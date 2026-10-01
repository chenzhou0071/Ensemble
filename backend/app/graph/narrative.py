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


OPEN_MARK = "[[npc:"
CLOSE_MARK = "[[/npc]]"


def _holdback_len(buf: str, marker: str) -> int:
    """buf 末尾可能是 marker 前缀（跨 chunk 截断）时需保留的字符数。"""
    for k in range(min(len(marker) - 1, len(buf)), 0, -1):
        if buf.endswith(marker[:k]):
            return k
    return 0


class IncrementalSegmenter:
    """流式叙事分段器：与 parse_segments 同一标记语法，处理跨 chunk 截断。

    只用于实时推送（展示层）；落库的权威分段由 parse_segments 在节点末尾生成。
    已知差异：输出不合法（标记未闭合）时两者兜底切分可能不同——重连后以落库分段为准。
    """

    def __init__(self) -> None:
        self._buf = ""
        self._speaker = "gm"

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self._buf += chunk
        out: list[tuple[str, str]] = []
        while self._buf:
            if self._speaker == "gm":
                idx = self._buf.find(OPEN_MARK)
                if idx == -1:
                    hold = _holdback_len(self._buf, OPEN_MARK)
                    emit = self._buf[: len(self._buf) - hold]
                    self._buf = self._buf[len(self._buf) - hold:]
                    if emit:
                        out.append(("gm", emit))
                    break
                emit, self._buf = self._buf[:idx], self._buf[idx:]
                if emit:
                    out.append(("gm", emit))
                end = self._buf.find("]]")
                if end == -1:
                    break  # 开标签跨 chunk：等待更多输入
                npc_id = self._buf[len(OPEN_MARK):end]
                self._speaker = f"npc:{npc_id}"
                self._buf = self._buf[end + 2:]
            else:
                idx = self._buf.find(CLOSE_MARK)
                if idx == -1:
                    hold = _holdback_len(self._buf, CLOSE_MARK)
                    emit = self._buf[: len(self._buf) - hold]
                    self._buf = self._buf[len(self._buf) - hold:]
                    if emit:
                        out.append((self._speaker, emit))
                    break
                emit, self._buf = self._buf[:idx], self._buf[idx + len(CLOSE_MARK):]
                if emit:
                    out.append((self._speaker, emit))
                self._speaker = "gm"
        return out

    def flush(self) -> list[tuple[str, str]]:
        """流结束时调用：剩余缓冲按当前说话人输出（未闭合标记的兜底）。"""
        if not self._buf:
            return []
        out = [(self._speaker, self._buf)]
        self._buf = ""
        return out
