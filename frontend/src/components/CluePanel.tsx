import type { CluePayload } from "../types";

export default function CluePanel({ clues }: { clues: CluePayload[] }) {
  return (
    <section className="panel">
      <h3>线索（{clues.length}）</h3>
      {clues.length === 0
        ? <p className="muted">尚未发现线索</p>
        : (
          <ul>
            {clues.map((c) => (
              <li key={c.clue_id}>{c.text || c.clue_id}</li>
            ))}
          </ul>
        )}
    </section>
  );
}
