import type { Session } from "../session";

export default function Room({ session, onLeave }: {
  session: Session;
  onLeave: () => void;
}) {
  return (
    <div className="room">
      <header className="room-header">
        <button onClick={onLeave}>← 回到大厅</button>
        <h2>{session.title}</h2>
      </header>
      <main className="room-main">
        <div className="room-story" />
      </main>
      <footer className="room-footer" />
    </div>
  );
}
