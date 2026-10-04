import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/rest";
import { WsClient } from "../api/ws";
import CharacterPanel from "../components/CharacterPanel";
import CluePanel from "../components/CluePanel";
import DiceLogPanel from "../components/DiceLogPanel";
import DiceOverlay from "../components/DiceOverlay";
import InputBar from "../components/InputBar";
import NarrationStream from "../components/NarrationStream";
import NpcPanel from "../components/NpcPanel";
import type { Session } from "../session";
import { useGame } from "../stores/game";
import type { ModuleDetail } from "../types";

export default function Room({ session, onLeave }: {
  session: Session;
  onLeave: () => void;
}) {
  const state = useGame();
  const [moduleInfo, setModuleInfo] = useState<ModuleDetail | null>(null);
  const clientRef = useRef<WsClient | null>(null);

  useEffect(() => {
    useGame.getState().reset();
    const client = new WsClient(session.campaignId, session.playerId, {
      onEvent: (evt) => useGame.getState().apply(evt),
      onStatus: (s) => useGame.getState().setConnected(s === "open"),
    });
    clientRef.current = client;
    client.connect();
    api.module(session.campaignId).then(setModuleInfo).catch(() => {});
    return () => client.close();
  }, [session.campaignId, session.playerId]);

  const npcNames = useMemo(() => {
    const map: Record<string, string> = {};
    moduleInfo?.npcs.forEach((n) => { map[n.id] = n.name; });
    return map;
  }, [moduleInfo]);

  const handleDicePlayed = useCallback(() => {
    useGame.getState().dicePlayed();
  }, []);

  return (
    <div className="room">
      <header className="room-header">
        <button onClick={onLeave}>← 回到大厅</button>
        <h2>{session.title}</h2>
        <span className={`conn-badge ${state.connected ? "open" : ""}`}>
          {state.connected ? "已连接" : "连接中…"}
        </span>
        <span className="turn-badge">
          回合 {state.turnId} · ${state.costUsd.toFixed(3)}
        </span>
      </header>
      {state.errorMessage && (
        <div className="error-banner">{state.errorMessage}</div>
      )}
      {state.notice && <div className="notice-banner">{state.notice}</div>}
      <main className="room-main">
        <NarrationStream segments={state.segments} live={state.live}
                         npcNames={npcNames} />
        <aside className="room-side">
          <CharacterPanel characters={state.characters as never[]} />
          {state.scene && (
            <section className="panel">
              <h3>所在位置</h3>
              <p className="scene-name">{state.scene.name}</p>
            </section>
          )}
          <NpcPanel sceneNpcs={state.scene?.npcs ?? []} knownNpcs={state.knownNpcs}
                    npcNames={npcNames} />
          <CluePanel clues={state.clues} />
          <DiceLogPanel diceLog={state.diceLog} />
        </aside>
      </main>
      <footer className="room-footer">
        <InputBar phase={state.phase} connected={state.connected}
                  onSubmit={(text) => clientRef.current?.sendInput(text)} />
      </footer>
      <DiceOverlay dice={state.diceQueue[0] ?? null} onDone={handleDicePlayed} />
    </div>
  );
}
