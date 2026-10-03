import { create } from "zustand";

import type {
  CluePayload, DicePayload, ScenePayload, Segment, WsEvent,
} from "../types";

export type Phase = "idle" | "resolving" | "collecting" | "paused" | "ended";

export type GameState = {
  phase: Phase;
  turnId: number;
  segments: Segment[];
  live: Segment[];
  scene: ScenePayload | null;
  sceneId: string | null;
  characters: unknown[];
  clues: CluePayload[];
  diceLog: DicePayload[];
  diceQueue: DicePayload[];
  actors: { player_id: string; text: string }[];
  notice: string | null;
  errorMessage: string | null;
  endingReached: string | null;
  costUsd: number;
};

export const initialState: GameState = {
  phase: "idle",
  turnId: 0,
  segments: [],
  live: [],
  scene: null,
  sceneId: null,
  characters: [],
  clues: [],
  diceLog: [],
  diceQueue: [],
  actors: [],
  notice: null,
  errorMessage: null,
  endingReached: null,
  costUsd: 0,
};

export function reduceEvent(state: GameState, evt: WsEvent): GameState {
  switch (evt.type) {
    case "token": {
      const { speaker, text, reset } = evt.payload;
      if (reset) return { ...state, live: [] };
      if (!speaker || !text) return state;
      const live = [...state.live];
      const last = live[live.length - 1];
      if (last && last.speaker === speaker) {
        live[live.length - 1] = { speaker, text: last.text + text };
      } else {
        live.push({ speaker, text });
      }
      return { ...state, live };
    }
    case "turn": {
      const { phase, turn_id, ending_reached } = evt.payload;
      const base: GameState = {
        ...state,
        phase,
        turnId: turn_id ?? state.turnId,
      };
      if (phase === "resolving") {
        base.live = [];
        base.errorMessage = null;
      }
      if (ending_reached) base.endingReached = ending_reached;
      return base;
    }
    case "state": {
      const p = evt.payload;
      const next: GameState = {
        ...state,
        turnId: p.turn_id,
        sceneId: p.scene_id,
        characters: p.characters,
        clues: p.clues_revealed,
        costUsd: p.cost_usd,
        endingReached: p.ending_reached ?? state.endingReached,
      };
      if (p.segments && p.segments.length > 0) {
        next.segments = p.segments;
        next.live = [];
      }
      if (p.dice) next.diceLog = p.dice;
      if (p.phase && state.phase === "idle") next.phase = p.phase as Phase;
      return next;
    }
    case "scene":
      return { ...state, scene: evt.payload, sceneId: evt.payload.scene_id };
    case "clue": {
      if (state.clues.some((c) => c.clue_id === evt.payload.clue_id)) return state;
      return { ...state, clues: [...state.clues, evt.payload] };
    }
    case "dice":
      return {
        ...state,
        diceLog: [...state.diceLog, evt.payload].slice(-20),
        diceQueue: [...state.diceQueue, evt.payload],
      };
    case "actor":
      return { ...state, actors: [...state.actors, evt.payload].slice(-20) };
    case "notice":
      return {
        ...state,
        notice: evt.payload.message ?? evt.payload.status ?? "提示",
      };
    case "error":
      return { ...state, errorMessage: evt.payload.message };
    default:
      return state;
  }
}

type GameStore = GameState & {
  connected: boolean;
  apply: (evt: WsEvent) => void;
  dicePlayed: () => void;
  setConnected: (v: boolean) => void;
  reset: () => void;
};

export const useGame = create<GameStore>((set) => ({
  ...initialState,
  connected: false,
  apply: (evt) => set((s) => reduceEvent(s, evt)),
  dicePlayed: () => set((s) => ({ diceQueue: s.diceQueue.slice(1) })),
  setConnected: (v) => set({ connected: v }),
  reset: () => set({ ...initialState, connected: false }),
}));
