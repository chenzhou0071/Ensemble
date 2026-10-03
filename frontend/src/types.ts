export type Segment = { speaker: string; text: string };

export type TokenPayload = { speaker?: string; text?: string; reset?: boolean };
export type DicePayload = {
  actor: string; skill: string; skill_value: number; difficulty: string;
  roll: number; level: string; seed: number; success: boolean;
};
export type TurnPayload = {
  phase: "resolving" | "collecting" | "ended" | "paused";
  turn_id?: number;
  ending_reached?: string | null;
};
export type ScenePayload = {
  scene_id: string; name: string; description: string; npcs: string[];
};
export type CluePayload = { clue_id: string; text: string };
export type StatePayload = {
  campaign_id: string; branch_id: string; turn_id: number;
  scene_id: string | null; characters: unknown[]; clues_revealed: CluePayload[];
  ending_reached: string | null; cost_usd: number;
  segments?: Segment[]; dice?: DicePayload[]; phase?: string;
};
export type NoticePayload = { message?: string; kind?: string; status?: string };
export type ErrorPayload = { message: string };

export type WsEvent =
  | { seq: number; type: "token"; visibility: string; payload: TokenPayload }
  | { seq: number; type: "dice"; visibility: string; payload: DicePayload }
  | { seq: number; type: "actor"; visibility: string;
      payload: { player_id: string; text: string } }
  | { seq: number; type: "scene"; visibility: string; payload: ScenePayload }
  | { seq: number; type: "turn"; visibility: string; payload: TurnPayload }
  | { seq: number; type: "state"; visibility: string; payload: StatePayload }
  | { seq: number; type: "clue"; visibility: string; payload: CluePayload }
  | { seq: number; type: "notice"; visibility: string; payload: NoticePayload }
  | { seq: number; type: "error"; visibility: string; payload: ErrorPayload };

export type ModuleInfo = { id: string; title: string; version: string; path: string };
export type CampaignInfo = {
  id: string; title: string; module_id: string; active_branch_id: string;
  created_at: string;
};
export type CreateResult = {
  campaign_id: string; branch_id: string; player_id: string; character_id: string;
};
export type CampaignDetail = {
  id: string; title: string; module_id: string; module_title: string;
  active_branch_id: string; scene_id: string | null; turn_id: number;
  cost_usd: number; players: { id: string; display_name: string }[];
  characters: unknown[]; clues_revealed: CluePayload[];
};
export type BranchInfo = {
  id: string; name: string; parent_branch_id: string | null;
  fork_turn_id: number | null; completed_turns: number; created_at: string;
};
export type Timeline = { active_branch_id: string; branches: BranchInfo[] };
export type ModuleDetail = {
  id: string; title: string;
  npcs: { id: string; name: string }[];
  endings: { id: string; condition: string }[];
};
