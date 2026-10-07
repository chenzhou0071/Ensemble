import type { DicePayload } from "../types";

export default function DiceLogPanel({ diceLog }: { diceLog: DicePayload[] }) {
  const rows = [...diceLog].reverse().slice(0, 5);
  return (
    <section className="panel">
      <h3>检定记录</h3>
      {rows.length === 0
        ? <p className="muted">尚无检定</p>
        : (
          <ul>
            {rows.map((d, i) => (
              <li key={i} className={d.success ? "ok" : "bad"}>
                {d.skill} d100={d.roll} · {d.level}
                {d.bonus ? ` · 奖励骰×${d.bonus}` : ""}
                {d.penalty ? ` · 惩罚骰×${d.penalty}` : ""}
              </li>
            ))}
          </ul>
        )}
    </section>
  );
}
