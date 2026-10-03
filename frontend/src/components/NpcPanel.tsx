export default function NpcPanel({ sceneNpcs, knownNpcs, npcNames }: {
  sceneNpcs: string[];
  knownNpcs: string[];
  npcNames: Record<string, string>;
}) {
  const known = sceneNpcs.filter((id) => knownNpcs.includes(id));
  return (
    <section className="panel">
      <h3>已结识人物</h3>
      {known.length === 0
        ? <p className="muted">本场景暂无已结识的人物</p>
        : (
          <ul>
            {known.map((id) => <li key={id}>{npcNames[id] ?? id}</li>)}
          </ul>
        )}
    </section>
  );
}
