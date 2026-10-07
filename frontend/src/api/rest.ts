import type {
  CampaignDetail, CampaignInfo, CreateResult, ModuleDetail, ModuleInfo, Timeline,
  UsageSummary,
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
  campaigns: (clientId: string) =>
    jsonFetch<CampaignInfo[]>(`/api/campaigns?client_id=${encodeURIComponent(clientId)}`),
  createCampaign: (moduleId: string, title: string, playerName: string, clientId: string) =>
    postJson<CreateResult>("/api/campaigns", {
      module_id: moduleId, title, player_name: playerName, client_id: clientId,
    }),
  campaign: (id: string, clientId: string) =>
    jsonFetch<CampaignDetail>(
      `/api/campaigns/${id}?client_id=${encodeURIComponent(clientId)}`),
  timeline: (id: string) => jsonFetch<Timeline>(`/api/campaigns/${id}/timeline`),
  switchBranch: (id: string, branchId: string) =>
    postJson<{ active_branch_id: string }>(`/api/campaigns/${id}/switch`, {
      branch_id: branchId,
    }),
  restore: (id: string, turnId: number) =>
    postJson<{ branch_id: string; name: string }>(`/api/campaigns/${id}/restore`, {
      turn_id: turnId,
    }),
  module: (id: string) => jsonFetch<ModuleDetail>(`/api/campaigns/${id}/module`),
  usage: (id: string) => jsonFetch<UsageSummary>(`/api/campaigns/${id}/usage`),
};
