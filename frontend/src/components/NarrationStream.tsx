import { useEffect, useRef } from "react";

import type { Segment } from "../types";

export default function NarrationStream({ segments, live, npcNames }: {
  segments: Segment[];
  live: Segment[];
  npcNames?: Record<string, string>;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  // 贴底跟随：新内容到达时自动滚到底；用户上翻回看时暂停跟随
  useEffect(() => {
    const el = boxRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  });

  function onScroll() {
    const el = boxRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  function render(seg: Segment, key: string, cursor = false) {
    const isNpc = seg.speaker.startsWith("npc:");
    const id = isNpc ? seg.speaker.slice(4) : "";
    return (
      <p key={key} className={`${isNpc ? "seg-npc" : "seg-gm"}${cursor ? " cursor" : ""}`}>
        {isNpc && <span className="npc-name">【{npcNames?.[id] ?? id}】</span>}
        {seg.text}
      </p>
    );
  }
  return (
    <div className="room-story" ref={boxRef} onScroll={onScroll}>
      {segments.map((s, i) => render(s, `s-${i}`))}
      {live.map((s, i) => render(s, `l-${i}`, i === live.length - 1))}
    </div>
  );
}
