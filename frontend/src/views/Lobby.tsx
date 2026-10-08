import { useEffect, useState } from "react";

import { api } from "../api/rest";
import { getClientId } from "../client";
import type { Session } from "../session";
import type { CampaignInfo, ModuleInfo } from "../types";

export default function Lobby({ onEnter }: { onEnter: (s: Session) => void }) {
  const [modules, setModules] = useState<ModuleInfo[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignInfo[]>([]);
  const [moduleId, setModuleId] = useState("");
  const [title, setTitle] = useState("");
  const [playerName, setPlayerName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.modules()
      .then((ms) => {
        setModules(ms);
        setModuleId(ms[0]?.id ?? "");
      })
      .catch((e) => setError(String(e)));
    api.campaigns(getClientId()).then(setCampaigns).catch(() => {});
  }, []);

  async function create() {
    const t = title.trim();
    const p = playerName.trim();
    if (!moduleId || busy || !t || !p) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.createCampaign(moduleId, t, p, getClientId());
      onEnter({ campaignId: r.campaign_id, playerId: r.player_id, title: t });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function continueCampaign(c: CampaignInfo) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const detail = await api.campaign(c.id, getClientId());
      const player = detail.players[0];       // 单人档：唯一玩家即本档玩家
      if (!player) throw new Error("战役没有玩家记录");
      onEnter({ campaignId: c.id, playerId: player.id, title: c.title });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lobby">
      <h1>Ensemble · AI 跑团</h1>
      {error && <div className="error-banner">{error}</div>}
      <section>
        <h2>新建战役</h2>
        <label>
          模组
          <select value={moduleId} onChange={(e) => setModuleId(e.target.value)}>
            {modules.map((m) => (
              <option key={m.id} value={m.id}>{m.title}</option>
            ))}
          </select>
        </label>
        <label>
          战役名
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          玩家名
          <input value={playerName} onChange={(e) => setPlayerName(e.target.value)} />
        </label>
        <button onClick={create}
                disabled={busy || !moduleId || !title.trim() || !playerName.trim()}>
          开始跑团
        </button>
      </section>
      <section>
        <h2>存档</h2>
        {campaigns.length === 0 && <p>暂无存档</p>}
        <ul>
          {campaigns.map((c) => (
            <li key={c.id}>
              <span>{c.title}（{c.module_id}）</span>
              <button onClick={() => continueCampaign(c)} disabled={busy}>继续</button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
