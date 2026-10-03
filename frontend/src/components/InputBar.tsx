import { useState } from "react";

import type { Phase } from "../stores/game";

export default function InputBar({ phase, connected, onSubmit }: {
  phase: Phase;
  connected: boolean;
  onSubmit: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const disabled = !connected || phase !== "collecting";
  const hint = !connected ? "连接中…"
    : phase === "collecting" ? "输入你的行动（回车提交）"
    : phase === "paused" ? "预算已熔断，暂停中"
    : phase === "ended" ? "故事已结束"
    : "GM 正在处理本回合…";

  function send() {
    const t = text.trim();
    if (!t || disabled) return;
    onSubmit(t);
    setText("");
  }

  return (
    <>
      <input value={text} placeholder={hint} disabled={disabled}
             onChange={(e) => setText(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
      <button onClick={send} disabled={disabled}>提交</button>
    </>
  );
}
