import { useEffect, useState } from "react";

import { api } from "../api/rest";
import type { UsageSummary } from "../types";

export default function CostPanel({ campaignId }: { campaignId: string }) {
  const [usage, setUsage] = useState<UsageSummary | null>(null);

  useEffect(() => {
    let alive = true;
    api.usage(campaignId)
      .then((d) => { if (alive) setUsage(d); })
      .catch(() => {});                       // 拉取失败静默隐藏，不阻塞房间
    return () => { alive = false; };
  }, [campaignId]);

  if (!usage) return null;
  const pct = usage.cap_usd > 0
    ? Math.min(100, Math.round((usage.totals.cost_usd / usage.cap_usd) * 100))
    : 0;
  return (
    <section className="panel">
      <h3>成本</h3>
      <p className="muted">
        ${usage.totals.cost_usd.toFixed(4)} / ${usage.cap_usd.toFixed(2)}（{pct}%）
      </p>
      <div className="cost-bar"><span style={{ width: `${pct}%` }} /></div>
      <ul>
        {usage.recent.slice(0, 5).map((r, i) => (
          <li key={i}>{r.role} · {r.model} · ${r.cost_usd.toFixed(4)}</li>
        ))}
      </ul>
    </section>
  );
}
