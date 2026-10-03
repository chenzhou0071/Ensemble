import { useState } from "react";

import Lobby from "./views/Lobby";
import Room from "./views/Room";
import { clearSession, loadSession, saveSession, type Session } from "./session";

export default function App() {
  const [session, setSession] = useState<Session | null>(() => loadSession());

  if (!session) {
    return (
      <Lobby
        onEnter={(s) => {
          saveSession(s);
          setSession(s);
        }}
      />
    );
  }
  return (
    <Room
      session={session}
      onLeave={() => {
        clearSession();
        setSession(null);
      }}
    />
  );
}
