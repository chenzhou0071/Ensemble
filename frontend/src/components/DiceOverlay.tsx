import { useEffect, useState } from "react";

import type { DicePayload } from "../types";

const LEVEL_LABEL: Record<string, string> = {
  critical: "大成功", extreme: "极难成功", hard: "困难成功",
  regular: "成功", fail: "失败", fumble: "大失败",
};

export default function DiceOverlay({ dice, onDone }: {
  dice: DicePayload | null;
  onDone: () => void;
}) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!dice) return;
    setDisplay(0);
    const started = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - started >= 1200) {
        setDisplay(dice.roll);
        clearInterval(timer);
        setTimeout(onDone, 600);
      } else {
        setDisplay(1 + Math.floor(Math.random() * 100));
      }
    }, 60);
    return () => clearInterval(timer);
  }, [dice, onDone]);

  if (!dice) return null;
  return (
    <div className="dice-overlay">
      <div className="dice-card">
        <div className="dice-who">
          {dice.actor} · {dice.skill}（{dice.skill_value}）
        </div>
        <div className={`dice-roll ${dice.success ? "ok" : "bad"}`}>{display}</div>
        <div className="dice-level">{LEVEL_LABEL[dice.level] ?? dice.level}</div>
      </div>
    </div>
  );
}
