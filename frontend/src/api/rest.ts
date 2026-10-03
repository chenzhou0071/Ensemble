import type {
  CampaignDetail, CampaignInfo, CreateResult, ModuleInfo, Timeline,
} from "../types";

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    throw new Error(`${resp.status}: ${await resp.text()}`);
  }
  return (await resp.json()) as T;
}

function postJson<T>(url: string, body: unknown): Promise<T> {
  return jsonFetch<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = {
  modules: () => jsonFetch<ModuleInfo[]>("/api/modules"),
  campaigns: () => jsonFetch<CampaignInfo[]>("/api/campaigns"),
  createCampaign: (moduleId: string, title: string, playerName: string) =>
    postJson<CreateResult>("/api/campaigns", {
      module_id: moduleId, title, player_name: playerName,
    }),
  campaign: (id: string) => jsonFetch<CampaignDetail>(`/api/campaigns/${id}`),
  timeline: (id: string) => jsonFetch<Timeline>(`/api/campaigns/${id}/timeline`),
  switchBranch: (id: string, branchId: string) =>
    postJson<{ active_branch_id: string }>(`/api/campaigns/${id}/switch`, {
      branch_id: branchId,
    }),
  restore: (id: string, turnId: number) =>
    postJson<{ branch_id: string; name: string }>(`/api/campaigns/${id}/restore`, {
      turn_id: turnId,
    }),
};
