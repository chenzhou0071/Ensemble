export default function NpcPanel({ sceneNpcs, npcNames }: {
  sceneNpcs: string[];
  npcNames: Record<string, string>;
}) {
  if (sceneNpcs.length === 0) return null;
  return (
    <section className="panel">
      <h3>在场 NPC</h3>
      <ul>
        {sceneNpcs.map((id) => <li key={id}>{npcNames[id] ?? id}</li>)}
      </ul>
    </section>
  );
}
