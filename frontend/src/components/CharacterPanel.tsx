type CharacterDto = {
  id: string; name: string; player_id: string;
  attributes: Record<string, number>; skills: Record<string, number>;
  hp: number; max_hp: number;
};

export default function CharacterPanel({ characters }: {
  characters: CharacterDto[];
}) {
  return (
    <section className="panel">
      <h3>角色</h3>
      {characters.length === 0 && <p className="muted">加载中…</p>}
      {characters.map((c) => (
        <div key={c.id} className="char-card">
          <div className="char-name">
            {c.name}<span className="hp">{c.hp}/{c.max_hp}</span>
          </div>
          <div>
            {Object.entries(c.attributes).map(([k, v]) => (
              <span key={k} className="chip">{k} {v}</span>
            ))}
          </div>
          <div>
            {Object.entries(c.skills).map(([k, v]) => (
              <span key={k} className="chip">{k} {v}</span>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
