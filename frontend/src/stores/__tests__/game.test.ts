import { describe, expect, it } from "vitest";

import { initialState, reduceEvent } from "../game";
import type { WsEvent } from "../../types";

function evt(type: WsEvent["type"], payload: unknown, seq = 1): WsEvent {
  return { seq, type, visibility: "all", payload } as WsEvent;
}

describe("reduceEvent", () => {
  it("accumulates token deltas by speaker and resets on reset", () => {
    let s = reduceEvent(initialState, evt("token", { speaker: "gm", text: "雾" }));
    s = reduceEvent(s, evt("token", { speaker: "gm", text: "气" }));
    s = reduceEvent(s, evt("token", { speaker: "npc:elder", text: "来" }));
    expect(s.live).toEqual([
      { speaker: "gm", text: "雾气" },
      { speaker: "npc:elder", text: "来" },
    ]);
    s = reduceEvent(s, evt("token", { reset: true }));
    expect(s.live).toEqual([]);
  });

  it("replaces segments with authoritative state snapshot and clears live", () => {
    let s = reduceEvent(initialState, evt("token", { speaker: "gm", text: "增量" }));
    s = reduceEvent(s, evt("state", {
      campaign_id: "c", branch_id: "b", turn_id: 1, scene_id: "square",
      characters: [], clues_revealed: [], ending_reached: null, cost_usd: 0.01,
      segments: [{ speaker: "gm", text: "权威分段" }],
    }));
    expect(s.segments).toEqual([{ speaker: "gm", text: "权威分段" }]);
    expect(s.live).toEqual([]);
    expect(s.costUsd).toBeCloseTo(0.01);
    expect(s.sceneId).toBe("square");
  });

  it("tracks acquainted npcs from the authoritative state snapshot", () => {
    const s = reduceEvent(initialState, evt("state", {
      campaign_id: "c", branch_id: "b", turn_id: 2, scene_id: "square",
      characters: [], clues_revealed: [], ending_reached: null, cost_usd: 0.02,
      known_npcs: ["elder"],
    }));
    expect(s.knownNpcs).toEqual(["elder"]);
  });

  it("bumps stateRev on each authoritative state snapshot", () => {
    let s = reduceEvent(initialState, evt("state", {
      campaign_id: "c", branch_id: "b", turn_id: 1, scene_id: "square",
      characters: [], clues_revealed: [], ending_reached: null, cost_usd: 0.01,
    }));
    expect(s.stateRev).toBe(1);
    s = reduceEvent(s, evt("state", {
      campaign_id: "c", branch_id: "b", turn_id: 2, scene_id: "square",
      characters: [], clues_revealed: [], ending_reached: null, cost_usd: 0.02,
    }));
    expect(s.stateRev).toBe(2);
  });

  it("queues dice for animation and logs them", () => {
    const dice = { actor: "pc_p1", skill: "侦查", skill_value: 50,
                   difficulty: "regular", roll: 12, level: "hard",
                   seed: 1, success: true };
    const s = reduceEvent(initialState, evt("dice", dice));
    expect(s.diceQueue).toHaveLength(1);
    expect(s.diceLog).toHaveLength(1);
  });

  it("replayed dice are logged but not queued for animation", () => {
    const dice = { actor: "pc_p1", skill: "侦查", skill_value: 50,
                   difficulty: "regular", roll: 12, level: "hard",
                   seed: 1, success: true };
    const s = reduceEvent(initialState, { ...evt("dice", dice), replay: true });
    expect(s.diceLog).toHaveLength(1);       // 历史回填日志
    expect(s.diceQueue).toHaveLength(0);     // 但不重播动画
  });

  it("deduplicates clues and tracks ending phase", () => {
    const clue = { clue_id: "clue_diary", text: "一本日记" };
    let s = reduceEvent(initialState, evt("clue", clue));
    s = reduceEvent(s, evt("clue", clue));
    expect(s.clues).toHaveLength(1);
    s = reduceEvent(s, evt("turn", { phase: "ended", ending_reached: "ending_break" }));
    expect(s.endingReached).toBe("ending_break");
    expect(s.phase).toBe("ended");
  });

  it("resolving clears live and previous error", () => {
    let s = reduceEvent(initialState, evt("error", { message: "boom" }));
    s = reduceEvent(s, evt("turn", { phase: "resolving", turn_id: 2 }));
    expect(s.errorMessage).toBeNull();
    expect(s.phase).toBe("resolving");
  });

  it("captures notice message or submit status", () => {
    let s = reduceEvent(initialState, evt("notice", { message: "已提交" }));
    expect(s.notice).toBe("已提交");
    s = reduceEvent(initialState, evt("notice", { kind: "submit", status: "deferred" }));
    expect(s.notice).toBe("deferred");
  });
});
