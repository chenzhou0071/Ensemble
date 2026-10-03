export default function EndingOverlay({ endingReached, condition, onLeave }: {
  endingReached: string | null;
  condition: string | undefined;
  onLeave: () => void;
}) {
  if (!endingReached) return null;
  return (
    <div className="ending-overlay">
      <div className="ending-card">
        <h2>故事已抵达结局</h2>
        <p>{condition ?? endingReached}</p>
        <button onClick={onLeave}>回到大厅</button>
      </div>
    </div>
  );
}
