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
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    if (!dice) return;
    setDisplay(0);
    setRevealed(false);                        // 跳动期间不揭晓结果
    const started = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - started >= 1200) {
        setDisplay(dice.roll);
        setRevealed(true);                     // 定格：揭晓等级与结果色
        clearInterval(timer);
        setTimeout(onDone, 600);
      } else {
        setDisplay(1 + Math.floor(Math.random() * 100));
      }
    }, 60);
    return () => clearInterval(timer);
  }, [dice, onDone]);

  if (!dice) return null;
  const rollClass = revealed ? `dice-roll ${dice.success ? "ok" : "bad"}` : "dice-roll";
  return (
    <div className="dice-overlay">
      <div className="dice-card">
        <div className="dice-who">
          {dice.actor} · {dice.skill}（{dice.skill_value}）
        </div>
        <div className={rollClass}>{display}</div>
        <div className="dice-level">{revealed ? LEVEL_LABEL[dice.level] ?? dice.level : "……"}</div>
      </div>
    </div>
  );
}
