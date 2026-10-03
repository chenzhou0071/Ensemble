import type { Segment } from "../types";

export default function NarrationStream({ segments, live, npcNames }: {
  segments: Segment[];
  live: Segment[];
  npcNames?: Record<string, string>;
}) {
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
    <div className="room-story">
      {segments.map((s, i) => render(s, `s-${i}`))}
      {live.map((s, i) => render(s, `l-${i}`, i === live.length - 1))}
    </div>
  );
}
