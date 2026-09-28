# Ensemble 后端核心（M1 地基 + M2 单机闭环）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可独立运行的 Ensemble 后端核心：规则引擎、模组加载、版本化存储、LLM 分级路由与记账、可插拔记忆、LangGraph 多 agent 编排（GM 主图 + NPC 子图）+ CLI 单机跑团（含断点续玩与预算熔断）。

**Architecture:** GM Supervisor 主图 + NPC 子图（Send 并行）；骰子纯代码执行（seed 可复现）；L2 领域库 append-only + 版本化；FakeLLM/录制回放保证测试零网络。

**Tech Stack:** Python 3.12+ / uv / LangGraph + langgraph-checkpoint-sqlite / Pydantic v2 / SQLModel + SQLite / openai SDK（OpenAI 兼容）/ pytest。

**依据规格:** `docs/superpowers/specs/2026-09-24-ensemble-design.md`（所有决策以该文档为准）

## Global Constraints

以下约束适用于本计划**每一个任务**，值均拷贝自规格原文：

- Python 3.12+；后端包管理用 uv；基础依赖：langgraph、langgraph-checkpoint-sqlite、pydantic>=2、pyyaml、sqlmodel、openai；测试依赖 pytest、pytest-cov
- 骰子实现固定为：`seed = secrets.randbits(64)` → `random.Random(seed)` → 掷骰；**读档默认重掷**；seed 必须随 DiceRecord 落库
- 关联键：`campaign_id`；分支 thread：`thread_id = {campaign_id}@{branch_id}`，主分支 `branch_id = "main"`
- L2 领域库 **append-only + 版本化**（所有事件与状态变更带 `branch_id + turn_id`，按"目标 turn 之前的最新版本"查询，不做物理删除）
- 模型分级路由：`gm` = qwen-plus（DashScope OpenAI 兼容端点）、`npc` = deepseek-chat、`extractor` = qwen-turbo；定价来自 `config/pricing.yaml`，**不得硬编码**
- 降级矩阵（规格 §8）与预算熔断阶梯 ①~④（规格 §9）语义固定：①记忆降档 ②NPC 收缩到 gm_decide 首位相关 NPC ③GM 换便宜模型 ④战役熔断暂停
- 叙事有序性：NPC 台词不独立外发；`gm_narrate` 统一编排。M2 用内联标记 `[[npc:<npc_id>]]台词[[/npc]]` 表达说话人，由 `parse_segments` 解析
- 失败不推进时回到 `wait_input`，本轮 pending 丢弃（与"读档重掷"语义一致）
- 覆盖率口径（规格 §11）：rules 100%；content 校验器每条规则正/反用例；storage 仓储契约测试全通过；graph 所有路由分支 + 每条降级路径 ≥1 用例
- 本计划**不含**：WS / TurnBuffer / 前端 / LangSmith / /metrics / Graphiti（分属 M3/M4/M5 计划）
- 所有命令在 Windows PowerShell 下执行，用 `;` 串联；工作目录统一为 `e:\pro\Ensemble`

---

## File Structure（本计划全部文件）

```
ensemble/
├── .gitignore                     # Task 1
├── docker-compose.yml             # Task 1（骨架，M4 完善）
├── config/
│   └── pricing.yaml               # Task 10
├── modules/
│   └── misty_hollow.yaml          # Task 23（示例模组，兼回放基线与演示内容）
├── backend/
│   ├── Dockerfile                 # Task 1
│   ├── pyproject.toml             # Task 1
│   ├── app/
│   │   ├── __init__.py            # Task 1（__version__）
│   │   ├── config.py              # Task 10（Settings / Pricing 加载）
│   │   ├── cli.py                 # Task 24
│   │   ├── rules/
│   │   │   ├── __init__.py
│   │   │   ├── dice.py            # Task 2
│   │   │   ├── check.py           # Task 3
│   │   │   └── character.py       # Task 3
│   │   ├── content/
│   │   │   ├── __init__.py
│   │   │   ├── schema.py          # Task 4
│   │   │   ├── validate.py        # Task 5
│   │   │   └── loader.py          # Task 6
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          # Task 7
│   │   │   ├── db.py              # Task 7
│   │   │   └── repo.py            # Task 7/8/9
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── client.py          # Task 11
│   │   │   ├── fakes.py           # Task 11（FakeLLM）
│   │   │   └── usage.py           # Task 12
│   │   ├── memory/
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # Task 13
│   │   │   └── journal.py         # Task 13
│   │   └── graph/
│   │       ├── __init__.py
│   │       ├── state.py           # Task 14
│   │       ├── schemas.py         # Task 14
│   │       ├── narrative.py       # Task 14
│   │       ├── nodes/
│   │       │   ├── __init__.py
│   │       │   ├── turn.py        # Task 15/16
│   │       │   ├── gm.py          # Task 17/18
│   │       │   └── memory.py      # Task 20
│   │       ├── npc.py             # Task 19
│   │       └── main.py            # Task 21
│   └── tests/
│       ├── conftest.py            # Task 14（公共 fixture）；Task 23 追加 --record
│       ├── fixtures/modules/      # Task 6 起
│       ├── fixtures/misty_hollow/ # Task 23（回放基线）
│       └── harness/replay.py      # Task 23
```

---

### Task 1: 仓库骨架与工程配置

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/tests/test_smoke.py`, `.gitignore`, `backend/Dockerfile`, `docker-compose.yml`

**Interfaces:**
- Consumes: 无
- Produces: 可运行的 `uv` 工程；`app.__version__`；后续任务均可 `cd backend; uv run pytest`

- [ ] **Step 1: 前置检查** —— 确认 Python 3.12+ 与 uv 已安装；若未装 uv：`winget install astral-sh.uv`（或 `pip install uv`）

- [ ] **Step 2: 创建 pyproject 与包骨架**

`backend/pyproject.toml`：
```toml
[project]
name = "ensemble-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "langgraph", "langgraph-checkpoint-sqlite",
  "pydantic>=2", "pyyaml", "sqlmodel", "openai",
]

[dependency-groups]
dev = ["pytest", "pytest-cov"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`backend/app/__init__.py`：留空（下一步再写内容）。
同时创建空目录与空 `__init__.py`：`backend/tests/`、`backend/app/rules/`、`backend/app/content/`、`backend/app/storage/`、`backend/app/llm/`、`backend/app/memory/`、`backend/app/graph/`、`backend/app/graph/nodes/`。

- [ ] **Step 3: 写冒烟测试（先失败）**

`backend/tests/test_smoke.py`：
```python
import app

def test_version_exposed():
    assert app.__version__ == "0.1.0"
```

- [ ] **Step 4: 安装依赖并验证失败**

Run: `cd backend; uv sync; uv run pytest -q`
Expected: FAIL —— `AttributeError: module 'app' has no attribute '__version__'`

- [ ] **Step 5: 最小实现**

`backend/app/__init__.py`：
```python
__version__ = "0.1.0"
```

- [ ] **Step 6: 验证通过**

Run: `cd backend; uv run pytest -q`
Expected: PASS（1 passed）

- [ ] **Step 7: 工程配套文件**

根目录 `.gitignore`：
```
__pycache__/
*.pyc
.venv/
.pytest_cache/
*.db
.env
node_modules/
```

`backend/Dockerfile`（最小占位，M4 完善）：
```dockerfile
FROM python:3.12-slim
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .
CMD ["python", "-c", "import app; print(app.__version__)"]
```

`docker-compose.yml`：
```yaml
services:
  backend:
    build: ./backend
    volumes:
      - ./backend:/srv
```

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/app backend/tests .gitignore backend/Dockerfile docker-compose.yml backend/uv.lock
git commit -m "chore: bootstrap backend skeleton with uv, pytest, docker placeholders"
```

---

### Task 2: 骰子模块（真随机 seed + 可复现）

**Files:**
- Create: `backend/app/rules/dice.py`, `backend/tests/rules/test_dice.py`

**Interfaces:**
- Consumes: 无
- Produces: `new_seed() -> int`；`roll_d100(seed: int) -> int`（1..100，确定性）。Task 3/16 依赖

- [ ] **Step 1: 写失败测试**

`backend/tests/rules/test_dice.py`：
```python
from app.rules.dice import new_seed, roll_d100

def test_roll_is_deterministic_for_same_seed():
    assert roll_d100(42) == roll_d100(42)

def test_roll_within_range_for_many_seeds():
    assert all(1 <= roll_d100(s) <= 100 for s in range(1000))

def test_new_seed_within_64bit():
    s = new_seed()
    assert 0 <= s < 2**64

def test_new_seed_varies():
    assert new_seed() != new_seed()
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/rules/test_dice.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.rules.dice'`

- [ ] **Step 3: 实现**

`backend/app/rules/dice.py`：
```python
"""骰子：secrets 生成真随机 seed，random.Random(seed) 保证结果可复现。"""
import random
import secrets


def new_seed() -> int:
    return secrets.randbits(64)


def roll_d100(seed: int) -> int:
    return random.Random(seed).randint(1, 100)
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/rules/test_dice.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/rules/dice.py backend/tests/rules/test_dice.py backend/app/rules/__init__.py
git commit -m "feat(rules): d100 dice with true-random reproducible seeds"
```

---

### Task 3: d100 检定引擎 + 角色卡

**Files:**
- Create: `backend/app/rules/check.py`, `backend/app/rules/character.py`, `backend/tests/rules/test_check.py`, `backend/tests/rules/test_character.py`

**Interfaces:**
- Consumes: `app.rules.dice.roll_d100(seed)`
- Produces:
  - `CheckDifficulty(StrEnum)`：`REGULAR="regular" / HARD="hard" / EXTREME="extreme"`
  - `SuccessLevel(StrEnum)`：`CRITICAL / EXTREME / HARD / REGULAR / FAIL / FUMBLE`
  - `CheckResult`（frozen dataclass）：`actor, skill, skill_value, difficulty, roll, seed, level, success`
  - `roll_check(actor: str, skill: str, skill_value: int, difficulty: CheckDifficulty, seed: int) -> CheckResult`
  - `Character` dataclass：`id, name, player_id, attributes: dict[str,int], skills: dict[str,int], hp, max_hp`；方法 `skill_value(skill) -> int`；`make_default_character(player_id: str, name: str) -> Character`
- 判定规则（写死）：`roll==1 → CRITICAL`；`roll>=96 → FUMBLE`；否则 `≤max(1,技能//5) → EXTREME`、`≤技能//2 → HARD`、`≤技能 → REGULAR`、其余 `FAIL`。`success = level 达到该 difficulty 要求`（regular 要求 REGULAR+，hard 要求 HARD+，extreme 要求 EXTREME+；CRITICAL 恒成功，FUMBLE 恒失败）

- [ ] **Step 1: 写失败测试**

`backend/tests/rules/test_check.py`：
```python
from app.rules.check import CheckDifficulty, SuccessLevel, roll_check

def make(skill_value, difficulty=CheckDifficulty.REGULAR, seed=1):
    return roll_check("pc_1", "潜行", skill_value, difficulty, seed)

def test_critical_on_natural_one(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 1)
    r = make(50)
    assert r.level is SuccessLevel.CRITICAL and r.success

def test_fumble_on_96_plus(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 96)
    r = make(90)
    assert r.level is SuccessLevel.FUMBLE and not r.success

def test_extreme_hard_regular_fail_bands(monkeypatch):
    for roll, expected in [(5, SuccessLevel.EXTREME), (25, SuccessLevel.HARD), (50, SuccessLevel.REGULAR), (51, SuccessLevel.FAIL)]:
        monkeypatch.setattr("app.rules.check.roll_d100", lambda seed, r=roll: r)
        assert make(50).level is expected

def test_difficulty_gate(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 25)  # HARD 级
    assert make(50, CheckDifficulty.HARD).success
    assert not make(50, CheckDifficulty.EXTREME).success

def test_result_carries_seed_and_roll():
    r = roll_check("pc_1", "聆听", 60, CheckDifficulty.REGULAR, seed=123456)
    assert r.seed == 123456 and 1 <= r.roll <= 100
```

`backend/tests/rules/test_character.py`：
```python
from app.rules.character import Character, make_default_character

def test_skill_lookup_falls_back_to_attribute():
    c = Character(id="c1", name="张探员", player_id="p1",
                  attributes={"力量": 60, "意志": 50}, skills={"侦查": 70}, hp=10, max_hp=10)
    assert c.skill_value("侦查") == 70
    assert c.skill_value("力量") == 60
    assert c.skill_value("不存在") == 0

def test_default_character_is_playable():
    c = make_default_character("p1", "张探员")
    assert c.skill_value("侦查") >= 40 and c.hp == c.max_hp
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/rules -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.rules.check'`

- [ ] **Step 3: 实现 check.py**

`backend/app/rules/check.py`：
```python
"""d100 检定：纯函数，LLM 不参与任何数值计算。"""
from dataclasses import dataclass
from enum import StrEnum

from app.rules.dice import roll_d100


class CheckDifficulty(StrEnum):
    REGULAR = "regular"
    HARD = "hard"
    EXTREME = "extreme"


class SuccessLevel(StrEnum):
    CRITICAL = "critical"
    EXTREME = "extreme"
    HARD = "hard"
    REGULAR = "regular"
    FAIL = "fail"
    FUMBLE = "fumble"


_RANK = {SuccessLevel.FUMBLE: 0, SuccessLevel.FAIL: 1, SuccessLevel.REGULAR: 2,
         SuccessLevel.HARD: 3, SuccessLevel.EXTREME: 4, SuccessLevel.CRITICAL: 5}
_REQUIRED = {CheckDifficulty.REGULAR: 2, CheckDifficulty.HARD: 3, CheckDifficulty.EXTREME: 4}


@dataclass(frozen=True)
class CheckResult:
    actor: str
    skill: str
    skill_value: int
    difficulty: CheckDifficulty
    roll: int
    seed: int
    level: SuccessLevel
    success: bool


def _level_for(roll: int, skill_value: int) -> SuccessLevel:
    if roll == 1:
        return SuccessLevel.CRITICAL
    if roll >= 96:
        return SuccessLevel.FUMBLE
    if roll <= max(1, skill_value // 5):
        return SuccessLevel.EXTREME
    if roll <= skill_value // 2:
        return SuccessLevel.HARD
    if roll <= skill_value:
        return SuccessLevel.REGULAR
    return SuccessLevel.FAIL


def roll_check(actor: str, skill: str, skill_value: int,
               difficulty: CheckDifficulty, seed: int) -> CheckResult:
    roll = roll_d100(seed)
    level = _level_for(roll, skill_value)
    if level is SuccessLevel.CRITICAL:
        success = True
    elif level is SuccessLevel.FUMBLE:
        success = False
    else:
        success = _RANK[level] >= _REQUIRED[difficulty]
    return CheckResult(actor, skill, skill_value, difficulty, roll, seed, level, success)
```

- [ ] **Step 4: 实现 character.py**

`backend/app/rules/character.py`：
```python
"""角色卡领域模型。"""
from dataclasses import dataclass, field


@dataclass
class Character:
    id: str
    name: str
    player_id: str | None
    attributes: dict[str, int] = field(default_factory=dict)
    skills: dict[str, int] = field(default_factory=dict)
    hp: int = 10
    max_hp: int = 10

    def skill_value(self, skill: str) -> int:
        return self.skills.get(skill, self.attributes.get(skill, 0))


def make_default_character(player_id: str, name: str) -> Character:
    """CLI 阶段的最小可用角色；正式建卡流程在 M3 计划实现。"""
    return Character(
        id=f"pc_{player_id}", name=name, player_id=player_id,
        attributes={"力量": 50, "敏捷": 55, "意志": 55, "智力": 60},
        skills={"侦查": 50, "聆听": 45, "潜行": 40, "话术": 45, "图书馆使用": 40},
        hp=10, max_hp=10,
    )
```

- [ ] **Step 5: 验证通过**

Run: `cd backend; uv run pytest tests/rules -q`
Expected: PASS（8 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/app/rules/check.py backend/app/rules/character.py backend/tests/rules
git commit -m "feat(rules): coc-lite d100 check engine and character model"
```

---

### Task 4: 模组 Schema（Pydantic）

**Files:**
- Create: `backend/app/content/schema.py`, `backend/tests/content/test_schema.py`

**Interfaces:**
- Consumes: 无
- Produces（字段即最终契约，Task 5/6/17/19/22 依赖）：
  - `ModuleMeta(id, title, author="", version="0.1", system="coc-lite")`
  - `Opening(narration, scene_id, player_goal="")`
  - `Scene(id, name, description="", npcs: list[str]=[], exits: list[str]=[], clues: list[str]=[])`
  - `NpcDef(id, name, persona, knowledge: list[str]=[], initial_attitude: int=50)`
  - `Clue(id, content, unlocks: list[str]=[])`（unlocks 元素格式 `scene:<id>` 或 `clue:<id>`）
  - `Ending(id, scene, condition)`
  - `Module(meta, opening, scenes, npcs, clues, endings)`；方法 `scene(sid) -> Scene`、`npc(nid) -> NpcDef`、`ending(eid) -> Ending`

- [ ] **Step 1: 写失败测试**

`backend/tests/content/test_schema.py`：
```python
import pytest
from app.content.schema import Module

MINIMAL = {
    "meta": {"id": "t1", "title": "测试模组"},
    "opening": {"narration": "你们来到村口。", "scene_id": "gate"},
    "scenes": [{"id": "gate", "name": "村口", "npcs": ["guard"], "exits": ["tavern"], "clues": []},
               {"id": "tavern", "name": "酒馆", "exits": []}],
    "npcs": [{"id": "guard", "name": "王守卫", "persona": "多疑"}],
    "clues": [],
    "endings": [{"id": "e1", "scene": "tavern", "condition": "揭开真相"}],
}

def test_parse_minimal_module_with_defaults():
    m = Module.model_validate(MINIMAL)
    assert m.meta.system == "coc-lite"
    assert m.npcs[0].initial_attitude == 50
    assert m.scenes[0].exits == ["tavern"]

def test_lookup_helpers():
    m = Module.model_validate(MINIMAL)
    assert m.scene("gate").name == "村口"
    assert m.npc("guard").name == "王守卫"

def test_lookup_missing_raises_key_error():
    m = Module.model_validate(MINIMAL)
    with pytest.raises(KeyError):
        m.scene("nowhere")
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/content/test_schema.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.content.schema'`

- [ ] **Step 3: 实现**

`backend/app/content/schema.py`：
```python
"""模组内容模型：内容与引擎分离，字段即公开契约。"""
from pydantic import BaseModel, Field


class ModuleMeta(BaseModel):
    id: str
    title: str
    author: str = ""
    version: str = "0.1"
    system: str = "coc-lite"


class Opening(BaseModel):
    narration: str
    scene_id: str
    player_goal: str = ""


class Scene(BaseModel):
    id: str
    name: str
    description: str = ""
    npcs: list[str] = Field(default_factory=list)
    exits: list[str] = Field(default_factory=list)
    clues: list[str] = Field(default_factory=list)


class NpcDef(BaseModel):
    id: str
    name: str
    persona: str
    knowledge: list[str] = Field(default_factory=list)
    initial_attitude: int = 50


class Clue(BaseModel):
    id: str
    content: str
    unlocks: list[str] = Field(default_factory=list)


class Ending(BaseModel):
    id: str
    scene: str
    condition: str


class Module(BaseModel):
    meta: ModuleMeta
    opening: Opening
    scenes: list[Scene]
    npcs: list[NpcDef]
    clues: list[Clue]
    endings: list[Ending]

    def scene(self, scene_id: str) -> Scene:
        for s in self.scenes:
            if s.id == scene_id:
                return s
        raise KeyError(f"scene not found: {scene_id}")

    def npc(self, npc_id: str) -> NpcDef:
        for n in self.npcs:
            if n.id == npc_id:
                return n
        raise KeyError(f"npc not found: {npc_id}")

    def ending(self, ending_id: str) -> Ending:
        for e in self.endings:
            if e.id == ending_id:
                return e
        raise KeyError(f"ending not found: {ending_id}")
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/content/test_schema.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/content/schema.py backend/tests/content
git commit -m "feat(content): module schema with lookup helpers"
```

---

### Task 5: 模组静态校验器

**Files:**
- Create: `backend/app/content/validate.py`, `backend/tests/content/test_validate.py`

**Interfaces:**
- Consumes: `app.content.schema.Module`
- Produces: `validate_module(module: Module) -> list[str]`（返回问题描述列表，空列表=合法；顺序稳定：重复 id → 引用 → 连通性 → 结局可达）

- [ ] **Step 1: 写失败测试（每条规则正/反用例）**

`backend/tests/content/test_validate.py`：
```python
from copy import deepcopy
from app.content.schema import Module, Scene
from app.content.validate import validate_module

BASE = {
    "meta": {"id": "t1", "title": "测试"},
    "opening": {"narration": "开场", "scene_id": "gate"},
    "scenes": [
        {"id": "gate", "name": "村口", "npcs": ["guard"], "exits": ["tavern"], "clues": []},
        {"id": "tavern", "name": "酒馆", "npcs": [], "exits": [], "clues": ["c1"]},
    ],
    "npcs": [{"id": "guard", "name": "王守卫", "persona": "多疑"}],
    "clues": [{"id": "c1", "content": "传闻", "unlocks": ["scene:tavern"]}],
    "endings": [{"id": "e1", "scene": "tavern", "condition": "真相"}],
}

def mod():
    return Module.model_validate(deepcopy(BASE))

def test_valid_module_has_no_issues():
    assert validate_module(mod()) == []

def test_duplicate_scene_id():
    d = mod()
    d.scenes[1].id = "gate"
    assert any("duplicate scene id" in e for e in validate_module(d))

def test_missing_scene_reference_in_exits():
    d = mod()
    d.scenes[0].exits = ["nowhere"]
    assert any("exit target not found" in e for e in validate_module(d))

def test_missing_npc_reference():
    d = mod()
    d.scenes[0].npcs = ["ghost"]
    assert any("scene npc not found" in e for e in validate_module(d))

def test_missing_clue_reference_in_scene():
    d = mod()
    d.scenes[1].clues = ["c9"]
    assert any("scene clue not found" in e for e in validate_module(d))

def test_bad_clue_unlock_format_and_target():
    d = mod()
    d.clues[0].unlocks = ["castle:x"]
    assert any("bad unlock format" in e for e in validate_module(d))
    d.clues[0].unlocks = ["scene:nowhere"]
    assert any("unlock target not found" in e for e in validate_module(d))

def test_opening_scene_must_exist():
    d = mod()
    d.opening.scene_id = "void"
    assert any("opening scene not found" in e for e in validate_module(d))

def test_unreachable_scene_detected():
    d = mod()
    d.scenes.append(Scene(id="island", name="孤岛"))
    assert any("unreachable scene: island" in e for e in validate_module(d))

def test_ending_scene_must_exist_and_be_reachable():
    d = mod()
    d.scenes.append(Scene(id="island", name="孤岛"))
    d.endings[0].scene = "island"
    assert any("ending scene unreachable: island" in e for e in validate_module(d))
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/content/test_validate.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.content.validate'`

- [ ] **Step 3: 实现**

`backend/app/content/validate.py`：
```python
"""模组静态可达性校验：坏模组必须在加载期暴露，而不是跑到一半炸。"""
from collections import deque

from app.content.schema import Module


def _duplicates(ids: list[str]) -> list[str]:
    seen, dup = set(), []
    for i in ids:
        if i in seen:
            dup.append(i)
        else:
            seen.add(i)
    return dup


def validate_module(module: Module) -> list[str]:
    issues: list[str] = []

    for kind, ids in [("scene", [s.id for s in module.scenes]),
                      ("npc", [n.id for n in module.npcs]),
                      ("clue", [c.id for c in module.clues]),
                      ("ending", [e.id for e in module.endings])]:
        for dup in _duplicates(ids):
            issues.append(f"duplicate {kind} id: {dup}")

    scene_ids = {s.id for s in module.scenes}
    npc_ids = {n.id for n in module.npcs}
    clue_ids = {c.id for c in module.clues}

    if module.opening.scene_id not in scene_ids:
        issues.append(f"opening scene not found: {module.opening.scene_id}")

    for s in module.scenes:
        for ex in s.exits:
            if ex not in scene_ids:
                issues.append(f"scene {s.id}: exit target not found: {ex}")
        for n in s.npcs:
            if n not in npc_ids:
                issues.append(f"scene {s.id}: scene npc not found: {n}")
        for c in s.clues:
            if c not in clue_ids:
                issues.append(f"scene {s.id}: scene clue not found: {c}")

    for c in module.clues:
        for u in c.unlocks:
            prefix, _, target = u.partition(":")
            if prefix not in ("scene", "clue") or not target:
                issues.append(f"clue {c.id}: bad unlock format: {u}")
            elif (prefix == "scene" and target not in scene_ids) or \
                 (prefix == "clue" and target not in clue_ids):
                issues.append(f"clue {c.id}: unlock target not found: {u}")

    if module.opening.scene_id in scene_ids:
        reachable, queue = {module.opening.scene_id}, deque([module.opening.scene_id])
        by_id = {s.id: s for s in module.scenes}
        while queue:
            cur = queue.popleft()
            for ex in by_id[cur].exits:
                if ex in by_id and ex not in reachable:
                    reachable.add(ex)
                    queue.append(ex)
        for sid in sorted(scene_ids - reachable):
            issues.append(f"unreachable scene: {sid}")
        for e in module.endings:
            if e.scene not in scene_ids:
                issues.append(f"ending {e.id}: ending scene not found: {e.scene}")
            elif e.scene not in reachable:
                issues.append(f"ending {e.id}: ending scene unreachable: {e.scene}")
    return issues
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/content/test_validate.py -q`
Expected: PASS（9 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/content/validate.py backend/tests/content/test_validate.py
git commit -m "feat(content): static module validator with per-rule tests"
```

---

### Task 6: 模组加载器（YAML → Module）

**Files:**
- Create: `backend/app/content/loader.py`, `backend/tests/fixtures/modules/valid_minimal.yaml`, `backend/tests/fixtures/modules/bad_unreachable.yaml`, `backend/tests/content/test_loader.py`

**Interfaces:**
- Consumes: `Module`（Task 4）、`validate_module`（Task 5）
- Produces: `ModuleValidationError(Exception)`（属性 `errors: list[str]`）；`load_module(path: str | Path) -> Module`

- [ ] **Step 1: 造 fixture 文件**

`backend/tests/fixtures/modules/valid_minimal.yaml`：
```yaml
meta: { id: t-min, title: 迷你模组, version: "0.1" }
opening: { narration: 你们来到村口。, scene_id: gate }
scenes:
  - { id: gate, name: 村口, npcs: [guard], exits: [tavern] }
  - { id: tavern, name: 酒馆, clues: [c1] }
npcs:
  - { id: guard, name: 王守卫, persona: 多疑的老兵, initial_attitude: 40 }
clues:
  - { id: c1, content: 酒馆里流传着磨坊的传闻, unlocks: [scene:tavern] }
endings:
  - { id: e1, scene: tavern, condition: 揭开真相 }
```

`backend/tests/fixtures/modules/bad_unreachable.yaml`：复制上述内容，追加孤岛场景并把结局指向它：
```yaml
endings:
  - { id: e1, scene: island, condition: 揭开真相 }
# scenes 中追加：- { id: island, name: 孤岛 }
```

- [ ] **Step 2: 写失败测试**

`backend/tests/content/test_loader.py`：
```python
from pathlib import Path
import pytest
from app.content.loader import ModuleValidationError, load_module

FIXTURES = Path(__file__).parent.parent / "fixtures" / "modules"

def test_loads_valid_module():
    m = load_module(FIXTURES / "valid_minimal.yaml")
    assert m.meta.id == "t-min"
    assert m.npc("guard").initial_attitude == 40

def test_invalid_module_raises_with_reasons():
    with pytest.raises(ModuleValidationError) as ei:
        load_module(FIXTURES / "bad_unreachable.yaml")
    assert any("unreachable" in e for e in ei.value.errors)
```

- [ ] **Step 3: 验证失败**

Run: `cd backend; uv run pytest tests/content/test_loader.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.content.loader'`

- [ ] **Step 4: 实现**

`backend/app/content/loader.py`：
```python
"""模组加载：YAML → Schema → 静态校验，校验不过直接拒绝加载。"""
from pathlib import Path

import yaml

from app.content.schema import Module
from app.content.validate import validate_module


class ModuleValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("module validation failed: " + "; ".join(errors))


def load_module(path: str | Path) -> Module:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    module = Module.model_validate(raw)
    issues = validate_module(module)
    if issues:
        raise ModuleValidationError(issues)
    return module
```

- [ ] **Step 5: 验证通过**

Run: `cd backend; uv run pytest tests/content -q`
Expected: PASS（全部 content 测试通过）

- [ ] **Step 6: Commit**

```bash
git add backend/app/content/loader.py backend/tests/fixtures backend/tests/content/test_loader.py
git commit -m "feat(content): yaml module loader with validation gate"
```

---

### Task 7: 存储层 —— 模型、引擎、战役与分支

**Files:**
- Create: `backend/app/storage/models.py`, `backend/app/storage/db.py`, `backend/app/storage/repo.py`, `backend/tests/storage/test_repo_campaigns.py`

**Interfaces:**
- Consumes: 无
- Produces（后续所有任务依赖，字段名固定）：
  - 表模型（SQLModel, table=True）：`Campaign(id, module_id, title, active_branch_id, created_at)`、`Branch(id, campaign_id, name, parent_branch_id: str|None, fork_turn_id: int|None, created_at)`、`Player(id, campaign_id, display_name, join_token)`、`CharacterStateRow(id, campaign_id, branch_id, turn_id, character_id, data_json)`、`GameEventRow(id, campaign_id, branch_id, turn_id, seq, type, visibility, payload_json, created_at)`、`DiceRecordRow(id, campaign_id, branch_id, turn_id, actor, skill, skill_value, difficulty, roll, level, seed, created_at)`、`StateSnapshotRow(id, campaign_id, branch_id, turn_id, data_json)`、`SummaryRow(id, campaign_id, branch_id, upto_turn, content, created_at)`、`UsageRow(id, campaign_id, branch_id, turn_id, role, model, tokens_in, tokens_out, cost_usd, latency_ms, created_at)`
  - `make_engine(sqlite_path: str) -> Engine`（`check_same_thread=False`）；`init_db(engine) -> None`
  - `SqliteRepository(engine)`：`create_campaign(module_id, title) -> Campaign`（自动建 `main` 分支并设 active）；`get_campaign(campaign_id) -> Campaign`；`get_branch(branch_id) -> Branch`；`create_branch(campaign_id, name, fork_turn_id, parent_branch_id) -> Branch`；`switch_branch(campaign_id, branch_id) -> Campaign`；`list_branches(campaign_id) -> list[Branch]`；`thread_id_for(branch) -> str`
  - 分支 id 规则（写死）：`Branch.id = f"{campaign_id}@{name}"`，且 `thread_id_for(branch) == branch.id`

- [ ] **Step 1: 写失败测试**

`backend/tests/storage/test_repo_campaigns.py`：
```python
import pytest
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

@pytest.fixture
def repo(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    return SqliteRepository(engine)

def test_create_campaign_makes_main_branch(repo):
    c = repo.create_campaign("misty-hollow", "迷雾谷")
    branches = repo.list_branches(c.id)
    assert len(branches) == 1
    main = branches[0]
    assert main.name == "main"
    assert main.id == f"{c.id}@main"
    assert c.active_branch_id == main.id

def test_thread_id_matches_branch_id(repo):
    c = repo.create_campaign("m", "t")
    b = repo.list_branches(c.id)[0]
    assert repo.thread_id_for(b) == b.id

def test_fork_branch_and_switch(repo):
    c = repo.create_campaign("m", "t")
    main = repo.list_branches(c.id)[0]
    fork = repo.create_branch(c.id, "b2", fork_turn_id=5, parent_branch_id=main.id)
    assert fork.id == f"{c.id}@b2" and fork.fork_turn_id == 5
    c2 = repo.switch_branch(c.id, fork.id)
    assert c2.active_branch_id == fork.id
    assert len(repo.list_branches(c.id)) == 2
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/storage/test_repo_campaigns.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.storage.db'`

- [ ] **Step 3: 实现 models.py**

`backend/app/storage/models.py`：
```python
"""L2 领域库表模型：append-only + 版本化（branch_id + turn_id）。"""
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(SQLModel, table=True):
    id: str = Field(primary_key=True)
    module_id: str
    title: str
    active_branch_id: str
    created_at: datetime = Field(default_factory=_now)


class Branch(SQLModel, table=True):
    id: str = Field(primary_key=True)  # f"{campaign_id}@{name}"，同时是 LangGraph thread_id
    campaign_id: str = Field(index=True)
    name: str
    parent_branch_id: str | None = None
    fork_turn_id: int | None = None
    created_at: datetime = Field(default_factory=_now)


class Player(SQLModel, table=True):
    id: str = Field(primary_key=True)
    campaign_id: str = Field(index=True)
    display_name: str
    join_token: str


class CharacterStateRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    turn_id: int
    character_id: str = Field(index=True)
    data_json: str


class GameEventRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    turn_id: int
    seq: int
    type: str
    visibility: str = "all"
    payload_json: str
    created_at: datetime = Field(default_factory=_now)


class DiceRecordRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    turn_id: int
    actor: str
    skill: str
    skill_value: int
    difficulty: str
    roll: int
    level: str
    seed: int
    created_at: datetime = Field(default_factory=_now)


class StateSnapshotRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    turn_id: int
    data_json: str


class SummaryRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    upto_turn: int
    content: str
    created_at: datetime = Field(default_factory=_now)


class UsageRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str
    turn_id: int
    role: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    created_at: datetime = Field(default_factory=_now)
```

- [ ] **Step 4: 实现 db.py**

`backend/app/storage/db.py`：
```python
"""SQLite 引擎与建表。"""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel


def make_engine(sqlite_path: str) -> Engine:
    return create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
```

- [ ] **Step 5: 实现 repo.py（战役与分支部分）**

`backend/app/storage/repo.py`：
```python
"""L2 领域仓储：append-only、版本化、分支隔离。"""
import uuid

from sqlmodel import Session, select

from app.storage.models import Branch, Campaign


class SqliteRepository:
    def __init__(self, engine):
        self.engine = engine

    # ---------- campaigns & branches ----------

    def create_campaign(self, module_id: str, title: str) -> Campaign:
        campaign_id = uuid.uuid4().hex[:12]
        branch = Branch(id=f"{campaign_id}@main", campaign_id=campaign_id, name="main")
        campaign = Campaign(id=campaign_id, module_id=module_id, title=title,
                            active_branch_id=branch.id)
        with Session(self.engine) as s:
            s.add(branch)
            s.add(campaign)
            s.commit()
            s.refresh(campaign)
        return campaign

    def get_campaign(self, campaign_id: str) -> Campaign:
        with Session(self.engine) as s:
            c = s.get(Campaign, campaign_id)
        if c is None:
            raise KeyError(f"campaign not found: {campaign_id}")
        return c

    def get_branch(self, branch_id: str) -> Branch | None:
        with Session(self.engine) as s:
            return s.get(Branch, branch_id)

    def create_branch(self, campaign_id: str, name: str, fork_turn_id: int,
                      parent_branch_id: str) -> Branch:
        branch = Branch(id=f"{campaign_id}@{name}", campaign_id=campaign_id, name=name,
                        fork_turn_id=fork_turn_id, parent_branch_id=parent_branch_id)
        with Session(self.engine) as s:
            s.add(branch)
            s.commit()
            s.refresh(branch)
        return branch

    def switch_branch(self, campaign_id: str, branch_id: str) -> Campaign:
        with Session(self.engine) as s:
            c = s.get(Campaign, campaign_id)
            c.active_branch_id = branch_id
            s.add(c)
            s.commit()
            s.refresh(c)
        return c

    def list_branches(self, campaign_id: str) -> list[Branch]:
        with Session(self.engine) as s:
            return list(s.exec(select(Branch).where(Branch.campaign_id == campaign_id)).all())

    def thread_id_for(self, branch: Branch) -> str:
        return branch.id
```

- [ ] **Step 6: 验证通过**

Run: `cd backend; uv run pytest tests/storage -q`
Expected: PASS（3 passed）

- [ ] **Step 7: Commit**

```bash
git add backend/app/storage backend/tests/storage
git commit -m "feat(storage): sqlite models and campaign/branch repository"
```

---

### Task 8: 仓储 —— 事件流与版本化读取

**Files:**
- Modify: `backend/app/storage/repo.py`（追加方法）
- Create: `backend/tests/storage/test_repo_events.py`

**Interfaces:**
- Consumes: Task 7 的 `SqliteRepository`
- Produces（追加到 `SqliteRepository`）：
  - `add_event(campaign_id, branch_id, turn_id, type: str, payload: dict, visibility: str = "all") -> int`（返回 seq，分支内自增从 1 开始）
  - `list_events(campaign_id, branch_id, upto_turn: int | None = None, types: list[str] | None = None) -> list[GameEventRow]`（按 seq 升序）
  - `append_state(campaign_id, branch_id, turn_id, data: dict) -> None`；`get_state_at(campaign_id, branch_id, turn_id) -> dict | None`（≤turn_id 的最新版本）
  - `append_character(campaign_id, branch_id, turn_id, character_id, data: dict) -> None`；`get_character_at(campaign_id, branch_id, turn_id, character_id) -> dict | None`；`list_characters_at(campaign_id, branch_id, turn_id) -> list[dict]`（每个角色取 ≤turn_id 最新版本）
  - `append_summary(campaign_id, branch_id, upto_turn, content) -> None`；`latest_summary(campaign_id, branch_id) -> SummaryRow | None`

- [ ] **Step 1: 写失败测试**

`backend/tests/storage/test_repo_events.py`：
```python
import json
import pytest
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

@pytest.fixture
def repo(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    return SqliteRepository(engine)

@pytest.fixture
def campaign(repo):
    return repo.create_campaign("m", "t")

def test_events_sequenced_and_filterable(repo, campaign):
    b = campaign.active_branch_id
    assert repo.add_event(campaign.id, b, 0, "narration", {"text": "开场"}) == 1
    assert repo.add_event(campaign.id, b, 1, "narration", {"text": "第一幕"}) == 2
    repo.add_event(campaign.id, b, 1, "check", {"text": "侦查成功"})
    evs = repo.list_events(campaign.id, b)
    assert [e.seq for e in evs] == [1, 2, 3]
    assert [e.turn_id for e in repo.list_events(campaign.id, b, upto_turn=0)] == [0]
    assert len(repo.list_events(campaign.id, b, types=["check"])) == 1
    assert json.loads(evs[0].payload_json)["text"] == "开场"

def test_versioned_state_reads(repo, campaign):
    b = campaign.active_branch_id
    repo.append_state(campaign.id, b, 0, {"scene_id": "gate"})
    repo.append_state(campaign.id, b, 3, {"scene_id": "tavern"})
    assert repo.get_state_at(campaign.id, b, 2)["scene_id"] == "gate"
    assert repo.get_state_at(campaign.id, b, 3)["scene_id"] == "tavern"
    assert repo.get_state_at(campaign.id, b, -1) is None

def test_versioned_character_reads(repo, campaign):
    b = campaign.active_branch_id
    repo.append_character(campaign.id, b, 0, "pc_1", {"hp": 10})
    repo.append_character(campaign.id, b, 3, "pc_1", {"hp": 6})
    repo.append_character(campaign.id, b, 0, "pc_2", {"hp": 10})
    assert repo.get_character_at(campaign.id, b, 2, "pc_1")["hp"] == 10
    assert repo.get_character_at(campaign.id, b, 3, "pc_1")["hp"] == 6
    assert sorted(c["hp"] for c in repo.list_characters_at(campaign.id, b, 2)) == [10, 10]

def test_summary_latest(repo, campaign):
    b = campaign.active_branch_id
    repo.append_summary(campaign.id, b, 3, "前三回合摘要")
    repo.append_summary(campaign.id, b, 6, "前六回合摘要")
    assert repo.latest_summary(campaign.id, b).upto_turn == 6
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/storage/test_repo_events.py -q`
Expected: FAIL —— `AttributeError: 'SqliteRepository' object has no attribute 'add_event'`

- [ ] **Step 3: 实现（追加到 repo.py 尾部）**

```python
    # ---------- events ----------

    def add_event(self, campaign_id: str, branch_id: str, turn_id: int, type: str,
                  payload: dict, visibility: str = "all") -> int:
        with Session(self.engine) as s:
            last = s.exec(select(GameEventRow).where(GameEventRow.branch_id == branch_id)
                          .order_by(GameEventRow.seq.desc())).first()
            seq = (last.seq + 1) if last else 1
            s.add(GameEventRow(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id,
                               seq=seq, type=type, visibility=visibility,
                               payload_json=json.dumps(payload, ensure_ascii=False)))
            s.commit()
        return seq

    def list_events(self, campaign_id: str, branch_id: str, upto_turn: int | None = None,
                    types: list[str] | None = None) -> list[GameEventRow]:
        q = select(GameEventRow).where(GameEventRow.branch_id == branch_id)
        if upto_turn is not None:
            q = q.where(GameEventRow.turn_id <= upto_turn)
        if types is not None:
            q = q.where(GameEventRow.type.in_(types))
        q = q.order_by(GameEventRow.seq)
        with Session(self.engine) as s:
            return list(s.exec(q).all())

    # ---------- versioned state ----------

    def append_state(self, campaign_id: str, branch_id: str, turn_id: int, data: dict) -> None:
        with Session(self.engine) as s:
            s.add(StateSnapshotRow(campaign_id=campaign_id, branch_id=branch_id,
                                   turn_id=turn_id,
                                   data_json=json.dumps(data, ensure_ascii=False)))
            s.commit()

    def get_state_at(self, campaign_id: str, branch_id: str, turn_id: int) -> dict | None:
        q = (select(StateSnapshotRow).where(StateSnapshotRow.branch_id == branch_id,
                                            StateSnapshotRow.turn_id <= turn_id)
             .order_by(StateSnapshotRow.turn_id.desc(), StateSnapshotRow.id.desc()))
        with Session(self.engine) as s:
            row = s.exec(q).first()
        return json.loads(row.data_json) if row else None

    def append_character(self, campaign_id: str, branch_id: str, turn_id: int,
                         character_id: str, data: dict) -> None:
        with Session(self.engine) as s:
            s.add(CharacterStateRow(campaign_id=campaign_id, branch_id=branch_id,
                                    turn_id=turn_id, character_id=character_id,
                                    data_json=json.dumps(data, ensure_ascii=False)))
            s.commit()

    def get_character_at(self, campaign_id: str, branch_id: str, turn_id: int,
                         character_id: str) -> dict | None:
        q = (select(CharacterStateRow)
             .where(CharacterStateRow.branch_id == branch_id,
                    CharacterStateRow.turn_id <= turn_id,
                    CharacterStateRow.character_id == character_id)
             .order_by(CharacterStateRow.turn_id.desc(), CharacterStateRow.id.desc()))
        with Session(self.engine) as s:
            row = s.exec(q).first()
        return json.loads(row.data_json) if row else None

    def list_characters_at(self, campaign_id: str, branch_id: str, turn_id: int) -> list[dict]:
        q = (select(CharacterStateRow)
             .where(CharacterStateRow.branch_id == branch_id,
                    CharacterStateRow.turn_id <= turn_id)
             .order_by(CharacterStateRow.character_id,
                       CharacterStateRow.turn_id.desc(), CharacterStateRow.id.desc()))
        with Session(self.engine) as s:
            rows = s.exec(q).all()
        best: dict[str, dict] = {}
        for row in rows:
            best.setdefault(row.character_id, json.loads(row.data_json))
        return list(best.values())

    # ---------- summaries ----------

    def append_summary(self, campaign_id: str, branch_id: str, upto_turn: int,
                       content: str) -> None:
        with Session(self.engine) as s:
            s.add(SummaryRow(campaign_id=campaign_id, branch_id=branch_id,
                             upto_turn=upto_turn, content=content))
            s.commit()

    def latest_summary(self, campaign_id: str, branch_id: str) -> SummaryRow | None:
        q = (select(SummaryRow).where(SummaryRow.branch_id == branch_id)
             .order_by(SummaryRow.upto_turn.desc(), SummaryRow.id.desc()))
        with Session(self.engine) as s:
            return s.exec(q).first()
```

同步修改文件头部 import 与 `json`：
```python
import json
import uuid

from sqlmodel import Session, select

from app.storage.models import (Branch, Campaign, CharacterStateRow, GameEventRow,
                                StateSnapshotRow, SummaryRow)
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/storage -q`
Expected: PASS（全部 storage 测试通过）

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/repo.py backend/tests/storage/test_repo_events.py
git commit -m "feat(storage): append-only events and versioned state reads"
```

---

### Task 9: 仓储 —— 骰子记录、用量记账、分支历史

**Files:**
- Modify: `backend/app/storage/repo.py`（追加方法）
- Create: `backend/tests/storage/test_repo_dice_usage.py`

**Interfaces:**
- Consumes: Task 7/8 的 `SqliteRepository`
- Produces（追加到 `SqliteRepository`）：
  - `add_dice_record(campaign_id, branch_id, turn_id, actor, skill, skill_value, difficulty, roll, level, seed) -> None`（显式字段，不 import rules 层）
  - `list_dice_records(campaign_id, branch_id, turn_id: int | None = None) -> list[DiceRecordRow]`
  - `record_usage(campaign_id, branch_id, turn_id, role, model, tokens_in, tokens_out, cost_usd, latency_ms) -> None`
  - `turn_token_total(campaign_id, branch_id, turn_id) -> int`（tokens_in + tokens_out 合计）
  - `campaign_cost_total(campaign_id) -> float`（全分支合计）
  - `branch_history_events(campaign_id, branch_id) -> list[GameEventRow]`（沿 parent 链拼接：父分支事件取 ≤fork_turn_id，自身取全部；按分支链由远及近、各自 seq 升序）

- [ ] **Step 1: 写失败测试**

`backend/tests/storage/test_repo_dice_usage.py`：
```python
import json
import pytest
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

@pytest.fixture
def repo(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    return SqliteRepository(engine)

@pytest.fixture
def campaign(repo):
    return repo.create_campaign("m", "t")

def test_dice_record_persists_seed(repo, campaign):
    b = campaign.active_branch_id
    repo.add_dice_record(campaign.id, b, 1, "pc_1", "侦查", 50, "regular", 23, "hard", 987654321)
    rows = repo.list_dice_records(campaign.id, b, turn_id=1)
    assert len(rows) == 1 and rows[0].seed == 987654321 and rows[0].roll == 23

def test_usage_totals(repo, campaign):
    b = campaign.active_branch_id
    repo.record_usage(campaign.id, b, 1, "gm", "qwen-plus", 100, 200, 0.002, 900)
    repo.record_usage(campaign.id, b, 1, "npc", "deepseek-chat", 50, 80, 0.0005, 700)
    repo.record_usage(campaign.id, b, 2, "gm", "qwen-plus", 10, 20, 0.0002, 800)
    assert repo.turn_token_total(campaign.id, b, 1) == 430
    assert repo.turn_token_total(campaign.id, b, 2) == 30
    assert abs(repo.campaign_cost_total(campaign.id) - 0.0027) < 1e-9

def test_fork_history_concatenates_parent_upto_fork_turn(repo, campaign):
    main = campaign.active_branch_id
    repo.add_event(campaign.id, main, 0, "narration", {"text": "开场"})
    repo.add_event(campaign.id, main, 1, "narration", {"text": "主分支 turn1"})
    fork = repo.create_branch(campaign.id, "b2", fork_turn_id=0, parent_branch_id=main)
    repo.add_event(campaign.id, fork.id, 1, "narration", {"text": "分叉 turn1"})
    texts = [json.loads(e.payload_json)["text"] for e in repo.branch_history_events(campaign.id, fork.id)]
    assert texts == ["开场", "分叉 turn1"]

def test_branch_events_are_isolated(repo, campaign):
    main = campaign.active_branch_id
    fork = repo.create_branch(campaign.id, "b2", fork_turn_id=0, parent_branch_id=main)
    repo.add_event(campaign.id, main, 1, "narration", {"text": "只属于 main"})
    assert repo.list_events(campaign.id, fork.id) == []
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/storage/test_repo_dice_usage.py -q`
Expected: FAIL —— `AttributeError: 'SqliteRepository' object has no attribute 'add_dice_record'`

- [ ] **Step 3: 实现（追加到 repo.py 尾部）**

```python
    # ---------- dice & usage ----------

    def add_dice_record(self, campaign_id: str, branch_id: str, turn_id: int, actor: str,
                        skill: str, skill_value: int, difficulty: str, roll: int,
                        level: str, seed: int) -> None:
        with Session(self.engine) as s:
            s.add(DiceRecordRow(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id,
                                actor=actor, skill=skill, skill_value=skill_value,
                                difficulty=difficulty, roll=roll, level=level, seed=seed))
            s.commit()

    def list_dice_records(self, campaign_id: str, branch_id: str,
                          turn_id: int | None = None) -> list[DiceRecordRow]:
        q = select(DiceRecordRow).where(DiceRecordRow.branch_id == branch_id)
        if turn_id is not None:
            q = q.where(DiceRecordRow.turn_id == turn_id)
        q = q.order_by(DiceRecordRow.id)
        with Session(self.engine) as s:
            return list(s.exec(q).all())

    def record_usage(self, campaign_id: str, branch_id: str, turn_id: int, role: str,
                     model: str, tokens_in: int, tokens_out: int, cost_usd: float,
                     latency_ms: int) -> None:
        with Session(self.engine) as s:
            s.add(UsageRow(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id,
                           role=role, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
                           cost_usd=cost_usd, latency_ms=latency_ms))
            s.commit()

    def turn_token_total(self, campaign_id: str, branch_id: str, turn_id: int) -> int:
        q = select(UsageRow).where(UsageRow.branch_id == branch_id, UsageRow.turn_id == turn_id)
        with Session(self.engine) as s:
            rows = s.exec(q).all()
        return sum(r.tokens_in + r.tokens_out for r in rows)

    def campaign_cost_total(self, campaign_id: str) -> float:
        q = select(UsageRow).where(UsageRow.campaign_id == campaign_id)
        with Session(self.engine) as s:
            rows = s.exec(q).all()
        return round(sum(r.cost_usd for r in rows), 6)

    # ---------- branch history ----------

    def branch_history_events(self, campaign_id: str, branch_id: str) -> list[GameEventRow]:
        chain: list[Branch] = []
        cur = self.get_branch(branch_id)
        while cur is not None:
            chain.append(cur)
            cur = self.get_branch(cur.parent_branch_id) if cur.parent_branch_id else None
        chain.reverse()
        out: list[GameEventRow] = []
        for i, b in enumerate(chain):
            upto = chain[i + 1].fork_turn_id if i + 1 < len(chain) else None
            out.extend(self.list_events(campaign_id, b.id, upto_turn=upto))
        return out
```

同步修改文件头部 import：
```python
from app.storage.models import (Branch, Campaign, CharacterStateRow, DiceRecordRow,
                                GameEventRow, StateSnapshotRow, SummaryRow, UsageRow)
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/storage -q`
Expected: PASS（全部 storage 测试通过）

- [ ] **Step 5: 里程碑检查 M1**

Run: `cd backend; uv run pytest -q --cov=app.rules --cov-report=term-missing`
Expected: 全部通过；rules 覆盖率 100%（未达则补测试后再 commit）

- [ ] **Step 6: Commit**

```bash
git add backend/app/storage/repo.py backend/tests/storage/test_repo_dice_usage.py
git commit -m "feat(storage): dice records, usage accounting, branch history"
```

---

### Task 10: 运行时配置与定价表

**Files:**
- Create: `backend/app/config.py`, `config/pricing.yaml`, `backend/tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces：
  - `PricingEntry(input_per_1k: float, output_per_1k: float)`；`Pricing(models: dict[str, PricingEntry])`；`load_pricing(path) -> Pricing`
  - `Settings`（字段写死，后续任务按名引用）：`sqlite_path="ensemble.db"`, `pricing_path="config/pricing.yaml"`, `gm_model="qwen-plus"`, `cheap_model="qwen-turbo"`, `npc_model="deepseek-chat"`, `extractor_model="qwen-turbo"`, `qwen_base_url`, `deepseek_base_url`, `qwen_api_key: str|None`, `deepseek_api_key: str|None`, `request_timeout_seconds=60`, `turn_window_seconds=60`, `turn_token_cap=30000`, `campaign_cost_cap_usd=2.0`
  - `load_settings() -> Settings`（读环境变量 `ENSEMBLE_SQLITE_PATH` / `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_config.py`：
```python
from pathlib import Path
from app.config import load_pricing, load_settings

def test_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    s = load_settings()
    assert s.gm_model == "qwen-plus" and s.turn_window_seconds == 60
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert load_settings().deepseek_api_key == "sk-test"

def test_pricing_loaded_from_yaml(tmp_path):
    p = tmp_path / "pricing.yaml"
    p.write_text("models:\n  m1: {input_per_1k: 0.001, output_per_1k: 0.002}\n", encoding="utf-8")
    pricing = load_pricing(p)
    assert pricing.models["m1"].output_per_1k == 0.002

def test_repo_pricing_covers_routed_models():
    repo_root = Path(__file__).resolve().parents[2]
    pricing = load_pricing(repo_root / "config" / "pricing.yaml")
    assert {"qwen-plus", "qwen-turbo", "deepseek-chat"} <= set(pricing.models)
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/test_config.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: 实现 config.py**

`backend/app/config.py`：
```python
"""运行时配置：环境变量 + config/pricing.yaml；价格与阈值全部可配置，不许硬编码。"""
import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class PricingEntry(BaseModel):
    input_per_1k: float
    output_per_1k: float


class Pricing(BaseModel):
    models: dict[str, PricingEntry]


def load_pricing(path: str | Path) -> Pricing:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Pricing.model_validate(raw)


class Settings(BaseModel):
    sqlite_path: str = "ensemble.db"
    pricing_path: str = "config/pricing.yaml"
    gm_model: str = "qwen-plus"
    cheap_model: str = "qwen-turbo"
    npc_model: str = "deepseek-chat"
    extractor_model: str = "qwen-turbo"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    qwen_api_key: str | None = None
    deepseek_api_key: str | None = None
    request_timeout_seconds: int = 60
    turn_window_seconds: int = 60
    turn_token_cap: int = 30000
    campaign_cost_cap_usd: float = 2.0


def load_settings() -> Settings:
    return Settings(
        sqlite_path=os.environ.get("ENSEMBLE_SQLITE_PATH", "ensemble.db"),
        qwen_api_key=os.environ.get("DASHSCOPE_API_KEY"),
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY"),
    )
```

- [ ] **Step 4: 实现 pricing.yaml**

`config/pricing.yaml`：
```yaml
# 价格仅用于成本估算，请按厂商官网更新（单位：美元 / 1K tokens）
models:
  qwen-plus: { input_per_1k: 0.0008, output_per_1k: 0.002 }
  qwen-turbo: { input_per_1k: 0.0003, output_per_1k: 0.0006 }
  deepseek-chat: { input_per_1k: 0.00027, output_per_1k: 0.0011 }
```

- [ ] **Step 5: 验证通过**

Run: `cd backend; uv run pytest tests/test_config.py -q`
Expected: PASS（3 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py config/pricing.yaml backend/tests/test_config.py
git commit -m "feat(config): settings and configurable pricing table"
```

---

### Task 11: LLM 客户端（分级路由 + 记账）+ FakeLLM

**Files:**
- Create: `backend/app/llm/client.py`, `backend/app/llm/fakes.py`, `backend/tests/llm/test_client.py`

**Interfaces:**
- Consumes: `Settings`、`Pricing`（Task 10）
- Produces：
  - `ChatMessage(BaseModel)`：`role: Literal["system","user","assistant"]`、`content: str`
  - `ChatResponse(BaseModel)`：`text: str`、`tokens_in: int`、`tokens_out: int`
  - `ChatModel(Protocol)`：`chat(messages: list[ChatMessage]) -> ChatResponse`
  - `LlmContext`（dataclass）：`campaign_id`、`branch_id`、`turn_id`
  - `Role = Literal["gm", "npc", "extractor"]`
  - `UsageSink(Protocol)`：`record_usage(campaign_id, branch_id, turn_id, role, model, tokens_in, tokens_out, cost_usd, latency_ms) -> None`
  - `compute_cost(pricing: Pricing, model: str, tokens_in: int, tokens_out: int) -> float`（未知模型返回 0.0）
  - `LLMClient(settings, pricing, usage_sink=None, model_factory=None)`；`chat(role, messages, ctx, cheap=False) -> str`
    - 路由：gm → `gm_model`（`cheap=True` 时用 `cheap_model`）；npc → `npc_model`；extractor → `extractor_model`；模型名前缀 `deepseek` → deepseek 端点/密钥，否则 qwen 端点/密钥
    - 工厂签名：`(model: str, base_url: str | None, api_key: str | None) -> ChatModel`；默认工厂返回 `OpenAICompatModel`
  - `OpenAICompatModel(api_key, base_url, model, timeout_seconds)`：真实 OpenAI 兼容客户端（本计划测试不触网，仅 CLI 联机时使用）
  - `FakeLLM(script: list[str | ChatResponse], tokens_in=10, tokens_out=20)`：按序返回脚本项；记录 `calls: list[list[ChatMessage]]`；脚本耗尽抛 `IndexError("FakeLLM script exhausted")`

- [ ] **Step 1: 写失败测试**

`backend/tests/llm/test_client.py`：
```python
import pytest
from app.config import Pricing, PricingEntry, Settings
from app.llm.client import ChatMessage, LLMClient, LlmContext, compute_cost
from app.llm.fakes import FakeLLM

MSGS = [ChatMessage(role="user", content="你好")]
CTX = LlmContext(campaign_id="c1", branch_id="c1@main", turn_id=1)

class RecordingSink:
    def __init__(self):
        self.rows = []
    def record_usage(self, *args, **kwargs):
        self.rows.append(kwargs)

def make_client(script_texts):
    settings = Settings()
    pricing = Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
        "deepseek-chat": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011),
    })
    sink = RecordingSink()
    built: dict[str, FakeLLM] = {}

    def factory(model, base_url, api_key):
        built[model] = FakeLLM(list(script_texts))
        return built[model]

    return LLMClient(settings, pricing, usage_sink=sink, model_factory=factory), sink, built

def test_routes_role_to_configured_model_and_records_usage():
    client, sink, built = make_client(["GM 的回复"])
    text = client.chat("gm", MSGS, CTX)
    assert text == "GM 的回复"
    assert "qwen-plus" in built
    row = sink.rows[0]
    assert row["role"] == "gm" and row["model"] == "qwen-plus"
    assert row["tokens_in"] == 10 and row["tokens_out"] == 20 and row["cost_usd"] > 0

def test_cheap_switch_uses_cheap_model():
    client, sink, built = make_client(["兜底回复"])
    client.chat("gm", MSGS, CTX, cheap=True)
    assert "qwen-turbo" in built and sink.rows[0]["model"] == "qwen-turbo"

def test_npc_role_uses_deepseek():
    client, sink, built = make_client(["NPC 的话"])
    client.chat("npc", MSGS, CTX)
    assert "deepseek-chat" in built

def test_cost_computation_and_unknown_model():
    pricing = Pricing(models={"a": PricingEntry(input_per_1k=0.001, output_per_1k=0.002)})
    assert compute_cost(pricing, "a", 1000, 500) == 0.002
    assert compute_cost(pricing, "unknown", 1000, 500) == 0.0

def test_fake_llm_exhaustion():
    f = FakeLLM([])
    with pytest.raises(IndexError):
        f.chat(MSGS)
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/llm/test_client.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.llm.client'`

- [ ] **Step 3: 实现 client.py**

`backend/app/llm/client.py`：
```python
"""LLM 客户端：按角色分级路由、统一记账；对测试完全可注入。"""
import time
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from pydantic import BaseModel

from app.config import Pricing, Settings

Role = Literal["gm", "npc", "extractor"]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatResponse(BaseModel):
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class ChatModel(Protocol):
    def chat(self, messages: list[ChatMessage]) -> ChatResponse: ...


@dataclass(frozen=True)
class LlmContext:
    campaign_id: str
    branch_id: str
    turn_id: int


class UsageSink(Protocol):
    def record_usage(self, campaign_id: str, branch_id: str, turn_id: int, role: str,
                     model: str, tokens_in: int, tokens_out: int, cost_usd: float,
                     latency_ms: int) -> None: ...


def compute_cost(pricing: Pricing, model: str, tokens_in: int, tokens_out: int) -> float:
    entry = pricing.models.get(model)
    if entry is None:
        return 0.0
    return round(tokens_in / 1000 * entry.input_per_1k + tokens_out / 1000 * entry.output_per_1k, 8)


class OpenAICompatModel:
    """OpenAI 兼容客户端（qwen / deepseek 均走此实现）。"""

    def __init__(self, api_key: str | None, base_url: str | None, model: str,
                 timeout_seconds: int = 60):
        from openai import OpenAI
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)

    def chat(self, messages: list[ChatMessage]) -> ChatResponse:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[m.model_dump() for m in messages],
        )
        usage = resp.usage
        return ChatResponse(
            text=resp.choices[0].message.content or "",
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
        )


ModelFactory = Callable[[str, "str | None", "str | None"], ChatModel]


def _default_factory(model: str, base_url: str | None, api_key: str | None) -> ChatModel:
    return OpenAICompatModel(api_key=api_key, base_url=base_url, model=model)


class LLMClient:
    def __init__(self, settings: Settings, pricing: Pricing,
                 usage_sink: UsageSink | None = None, model_factory: ModelFactory | None = None):
        self._settings = settings
        self._pricing = pricing
        self._usage_sink = usage_sink
        self._factory: ModelFactory = model_factory or _default_factory

    def chat(self, role: Role, messages: list[ChatMessage], ctx: LlmContext,
             cheap: bool = False) -> str:
        model, base_url, api_key = self._resolve(role, cheap)
        model_obj = self._factory(model, base_url, api_key)
        start = time.perf_counter()
        resp = model_obj.chat(messages)
        latency_ms = int((time.perf_counter() - start) * 1000)
        cost = compute_cost(self._pricing, model, resp.tokens_in, resp.tokens_out)
        if self._usage_sink is not None:
            self._usage_sink.record_usage(ctx.campaign_id, ctx.branch_id, ctx.turn_id,
                                          role, model, resp.tokens_in, resp.tokens_out,
                                          cost, latency_ms)
        return resp.text

    def _resolve(self, role: Role, cheap: bool) -> tuple[str, str | None, str | None]:
        if role == "gm":
            model = self._settings.cheap_model if cheap else self._settings.gm_model
        elif role == "npc":
            model = self._settings.npc_model
        else:
            model = self._settings.extractor_model
        if model.startswith("deepseek"):
            return model, self._settings.deepseek_base_url, self._settings.deepseek_api_key
        return model, self._settings.qwen_base_url, self._settings.qwen_api_key
```

- [ ] **Step 4: 实现 fakes.py**

`backend/app/llm/fakes.py`：
```python
"""测试与开发用的假模型。"""
from app.llm.client import ChatMessage, ChatResponse


class FakeLLM:
    """脚本化假模型：按顺序吐响应，记录收到的消息。"""

    def __init__(self, script: list[str | ChatResponse], tokens_in: int = 10,
                 tokens_out: int = 20):
        self.script = list(script)
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.index = 0
        self.calls: list[list[ChatMessage]] = []

    def chat(self, messages: list[ChatMessage]) -> ChatResponse:
        self.calls.append(messages)
        if self.index >= len(self.script):
            raise IndexError("FakeLLM script exhausted")
        item = self.script[self.index]
        self.index += 1
        if isinstance(item, ChatResponse):
            return item
        return ChatResponse(text=item, tokens_in=self.tokens_in, tokens_out=self.tokens_out)
```

- [ ] **Step 5: 验证通过**

Run: `cd backend; uv run pytest tests/llm -q`
Expected: PASS（5 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/app/llm backend/tests/llm
git commit -m "feat(llm): role-routed client with usage accounting and fake model"
```

---

### Task 12: 预算熔断（BudgetGuard）

**Files:**
- Create: `backend/app/llm/usage.py`, `backend/tests/llm/test_usage.py`

**Interfaces:**
- Consumes: `Settings`（Task 10）
- Produces：
  - `BudgetLevel(StrEnum)`：`OK="ok" / TIGHT="tight" / EXCEEDED="exceeded" / PAUSED="paused"`
  - `BudgetGuard(settings)`；`check(turn_tokens: int, campaign_cost_usd: float) -> BudgetLevel`
  - 判定规则（写死）：`cost >= cap → PAUSED`；`turn_tokens >= cap → EXCEEDED`；`turn_tokens >= 0.7*cap 或 cost >= 0.7*cap → TIGHT`；否则 `OK`
  - 语义映射：TIGHT → 熔断阶梯①②；EXCEEDED → ③（GM 换便宜模型）；PAUSED → ④（战役暂停，不再推进回合）

- [ ] **Step 1: 写失败测试**

`backend/tests/llm/test_usage.py`：
```python
from app.config import Settings
from app.llm.usage import BudgetGuard, BudgetLevel

def guard():
    return BudgetGuard(Settings(turn_token_cap=100, campaign_cost_cap_usd=1.0))

def test_ok_below_thresholds():
    assert guard().check(turn_tokens=0, campaign_cost_usd=0.0) is BudgetLevel.OK
    assert guard().check(turn_tokens=69, campaign_cost_usd=0.69) is BudgetLevel.OK

def test_tight_at_70_percent():
    assert guard().check(turn_tokens=70, campaign_cost_usd=0.0) is BudgetLevel.TIGHT
    assert guard().check(turn_tokens=0, campaign_cost_usd=0.7) is BudgetLevel.TIGHT

def test_exceeded_at_turn_token_cap():
    assert guard().check(turn_tokens=100, campaign_cost_usd=0.0) is BudgetLevel.EXCEEDED

def test_paused_at_campaign_cost_cap():
    assert guard().check(turn_tokens=0, campaign_cost_usd=1.0) is BudgetLevel.PAUSED
    assert guard().check(turn_tokens=999, campaign_cost_usd=1.0) is BudgetLevel.PAUSED
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/llm/test_usage.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.llm.usage'`

- [ ] **Step 3: 实现**

`backend/app/llm/usage.py`：
```python
"""预算熔断：事前约束（阶梯①②③④语义见设计规格 §9）。"""
from enum import StrEnum

from app.config import Settings


class BudgetLevel(StrEnum):
    OK = "ok"              # 正常
    TIGHT = "tight"        # 阶梯①②：记忆降档 + NPC 收缩到首位
    EXCEEDED = "exceeded"  # 阶梯③：GM 换便宜模型兜底
    PAUSED = "paused"      # 阶梯④：战役熔断暂停


class BudgetGuard:
    def __init__(self, settings: Settings):
        self.turn_cap = settings.turn_token_cap
        self.cost_cap = settings.campaign_cost_cap_usd

    def check(self, turn_tokens: int, campaign_cost_usd: float) -> BudgetLevel:
        if campaign_cost_usd >= self.cost_cap:
            return BudgetLevel.PAUSED
        if turn_tokens >= self.turn_cap:
            return BudgetLevel.EXCEEDED
        if turn_tokens >= 0.7 * self.turn_cap or campaign_cost_usd >= 0.7 * self.cost_cap:
            return BudgetLevel.TIGHT
        return BudgetLevel.OK
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/llm/test_usage.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/usage.py backend/tests/llm/test_usage.py
git commit -m "feat(llm): budget guard with tiered degradation levels"
```

---

### Task 13: 记忆服务（可插拔接口 + JournalMemory）

**Files:**
- Create: `backend/app/memory/base.py`, `backend/app/memory/journal.py`, `backend/tests/memory/test_journal.py`

**Interfaces:**
- Consumes: `SqliteRepository`（Task 8）、`ChatMessage`（Task 11）
- Produces：
  - `base.py`：`MemoryEvent(type: str, text: str, turn_id: int, visibility: str = "all")`；`MemoryHit(text: str, turn_id: int)`；`MemoryService(Protocol)`：`write_event(campaign_id, branch_id, event) -> None`、`search(campaign_id, branch_id, query: str, limit: int = 5) -> list[MemoryHit]`、`get_context(campaign_id, branch_id, budget_chars: int = 1200) -> str`、`update_summaries(campaign_id, branch_id, turn_id: int) -> None`
  - `journal.py`：`SUMMARY_TRIGGER_EVENTS = 12`；`JournalMemory(repo, summarizer: Callable[[list[ChatMessage]], str] | None = None)`
    - `write_event`：事件写入 L2 事件表，`type=f"memory:{event.type}"`，`payload={"text": event.text}`
    - `search`：关键词（≥2 字，最多 4 个）子串匹配 `payload.text`，按命中数、近因排序
    - `get_context`：`【前情摘要】+【近期事件】`拼装，截断到 `budget_chars`
    - `update_summaries`：新事件数 ≥ `SUMMARY_TRIGGER_EVENTS` 或从未有摘要时生成；`summarizer` 为 None 时用模板兜底（拼接事件文本，截 300 字）

- [ ] **Step 1: 写失败测试**

`backend/tests/memory/test_journal.py`：
```python
import pytest
from app.memory.base import MemoryEvent
from app.memory.journal import JournalMemory
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

@pytest.fixture
def env(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    campaign = repo.create_campaign("m", "t")
    return repo, campaign

def test_write_event_and_search(env):
    repo, campaign = env
    mem = JournalMemory(repo)
    mem.write_event(campaign.id, campaign.active_branch_id,
                    MemoryEvent(type="clue", text="磨坊夜里传出哭声", turn_id=1))
    mem.write_event(campaign.id, campaign.active_branch_id,
                    MemoryEvent(type="npc", text="王守卫不喜欢陌生人", turn_id=1))
    hits = mem.search(campaign.id, campaign.active_branch_id, "磨坊 哭声")
    assert hits and "磨坊" in hits[0].text and hits[0].turn_id == 1

def test_search_no_match_returns_empty(env):
    repo, campaign = env
    mem = JournalMemory(repo)
    mem.write_event(campaign.id, campaign.active_branch_id,
                    MemoryEvent(type="clue", text="无关内容", turn_id=1))
    assert mem.search(campaign.id, campaign.active_branch_id, "磨坊") == []

def test_get_context_includes_summary_and_recent(env):
    repo, campaign = env
    b = campaign.active_branch_id
    repo.append_summary(campaign.id, b, 3, "已有摘要")
    mem = JournalMemory(repo)
    mem.write_event(campaign.id, b, MemoryEvent(type="note", text="最新事件", turn_id=4))
    ctx = mem.get_context(campaign.id, b)
    assert "已有摘要" in ctx and "最新事件" in ctx

def test_update_summaries_uses_summarizer_and_threshold(env):
    repo, campaign = env
    b = campaign.active_branch_id
    calls = []
    def summarizer(messages):
        calls.append(messages)
        return "压缩后的摘要"
    mem = JournalMemory(repo, summarizer=summarizer)
    for i in range(12):
        mem.write_event(campaign.id, b, MemoryEvent(type="note", text=f"事件{i}", turn_id=i // 3))
    mem.update_summaries(campaign.id, b, turn_id=3)
    assert repo.latest_summary(campaign.id, b).content == "压缩后的摘要"
    assert len(calls) == 1

def test_update_summaries_below_threshold_skips(env):
    repo, campaign = env
    b = campaign.active_branch_id
    repo.append_summary(campaign.id, b, 0, "旧摘要")
    mem = JournalMemory(repo)
    mem.write_event(campaign.id, b, MemoryEvent(type="note", text="一条新事件", turn_id=1))
    mem.update_summaries(campaign.id, b, turn_id=1)
    assert repo.latest_summary(campaign.id, b).content == "旧摘要"  # 未触发新摘要
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/memory -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.memory.base'`

- [ ] **Step 3: 实现 base.py**

`backend/app/memory/base.py`：
```python
"""记忆服务契约：M2 用事件日志 + 滚动摘要；二阶段 Graphiti 适配器实现同一协议。"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MemoryEvent:
    type: str
    text: str
    turn_id: int
    visibility: str = "all"


@dataclass(frozen=True)
class MemoryHit:
    text: str
    turn_id: int


class MemoryService(Protocol):
    def write_event(self, campaign_id: str, branch_id: str, event: MemoryEvent) -> None: ...
    def search(self, campaign_id: str, branch_id: str, query: str,
               limit: int = 5) -> list[MemoryHit]: ...
    def get_context(self, campaign_id: str, branch_id: str, budget_chars: int = 1200) -> str: ...
    def update_summaries(self, campaign_id: str, branch_id: str, turn_id: int) -> None: ...
```

- [ ] **Step 4: 实现 journal.py**

`backend/app/memory/journal.py`：
```python
"""JournalMemory：事件日志 + 滚动摘要 + 简单检索（MVP 记忆实现）。"""
import json
import re
from typing import Callable

from app.llm.client import ChatMessage
from app.memory.base import MemoryEvent, MemoryHit

SUMMARY_TRIGGER_EVENTS = 12
_SUMMARY_PROMPT = (
    "你是跑团记录员。把给定事件压缩成不超过 300 字的前情摘要，"
    "保留关键人物、地点、线索与未解决的悬念。只输出摘要正文。"
)


class JournalMemory:
    def __init__(self, repo, summarizer: Callable[[list[ChatMessage]], str] | None = None):
        self._repo = repo
        self._summarizer = summarizer

    def write_event(self, campaign_id: str, branch_id: str, event: MemoryEvent) -> None:
        self._repo.add_event(campaign_id, branch_id, event.turn_id,
                             type=f"memory:{event.type}", payload={"text": event.text},
                             visibility=event.visibility)

    def search(self, campaign_id: str, branch_id: str, query: str,
               limit: int = 5) -> list[MemoryHit]:
        keywords = [k for k in re.split(r"[\s，。！？、,.!?]+", query) if len(k) >= 2][:4]
        if not keywords:
            keywords = [query]
        scored = []
        for row in self._repo.list_events(campaign_id, branch_id):
            text = json.loads(row.payload_json).get("text", "")
            score = sum(1 for k in keywords if k in text)
            if score > 0:
                scored.append((score, row.turn_id, row.seq, text))
        scored.sort(key=lambda t: (-t[0], -t[1], -t[2]))
        return [MemoryHit(text=t[3], turn_id=t[1]) for t in scored[:limit]]

    def get_context(self, campaign_id: str, branch_id: str, budget_chars: int = 1200) -> str:
        parts: list[str] = []
        summary = self._repo.latest_summary(campaign_id, branch_id)
        if summary:
            parts.append(f"【前情摘要】{summary.content}")
        events = self._repo.list_events(campaign_id, branch_id)[-8:]
        recent = [json.loads(e.payload_json).get("text", "") for e in events]
        if recent:
            parts.append("【近期事件】\n" + "\n".join(f"- {t}" for t in recent))
        return "\n".join(parts)[:budget_chars]

    def update_summaries(self, campaign_id: str, branch_id: str, turn_id: int) -> None:
        last = self._repo.latest_summary(campaign_id, branch_id)
        start = (last.upto_turn + 1) if last else 0
        events = [e for e in self._repo.list_events(campaign_id, branch_id, upto_turn=turn_id)
                  if e.turn_id >= start]
        if not events:
            return
        if last is not None and len(events) < SUMMARY_TRIGGER_EVENTS:
            return
        texts = [json.loads(e.payload_json).get("text", "") for e in events]
        body = "\n".join(t for t in texts if t)
        if self._summarizer is not None:
            prior = f"已有摘要：{last.content}\n" if last else ""
            content = self._summarizer([
                ChatMessage(role="system", content=_SUMMARY_PROMPT),
                ChatMessage(role="user", content=f"{prior}新事件：\n{body}"),
            ])
        else:
            content = (f"{last.content} " if last else "") + body
            content = content.strip()[:300]
        self._repo.append_summary(campaign_id, branch_id, upto_turn=turn_id, content=content)
```

- [ ] **Step 5: 验证通过**

Run: `cd backend; uv run pytest tests/memory -q`
Expected: PASS（5 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/app/memory backend/tests/memory
git commit -m "feat(memory): pluggable memory protocol with journal implementation"
```

---

### Task 14: 图状态、决策 Schema、叙事分段解析

**Files:**
- Create: `backend/app/graph/state.py`, `backend/app/graph/schemas.py`, `backend/app/graph/narrative.py`
- Create: `backend/tests/conftest.py`（公共 fixture：`mini_module` / `repo` / `campaign`）
- Test: `backend/tests/graph/test_state.py`, `backend/tests/graph/test_schemas.py`, `backend/tests/graph/test_narrative.py`

**Interfaces:**
- Consumes: `CheckDifficulty`（Task 3）、`SqliteRepository`（Task 7）
- Produces：
  - `TurnInput(player_id, character_id, text, submitted_at="")`；`TurnInputs(turn_id, inputs=[], skipped=[])`（Pydantic）
  - `merge_dict(current, update) -> dict`：空 dict 表示清空（用于 `npc_reactions` / `degraded` 通道）
  - `GameState(TypedDict, total=False)` 字段（**全计划固定命名**）：`campaign_id, branch_id, thread_id, turn_id, is_opening, scene_id, npc_attitudes: dict[str,int], characters: dict[str,dict], budget_level, player_inputs: list[dict], decision: dict|None, decision_raw: str, check_results: list[dict], memory_context: str, npc_reactions: Annotated[dict[str,dict], merge_dict], narration: str, narration_segments: list[dict], error: str|None, degraded: Annotated[dict[str,bool], merge_dict]`
  - `schemas.py`：`CheckRequest(actor, skill, difficulty=REGULAR)`、`NpcTrigger(npc_id, trigger="")`、`SceneTransition(to_scene, reason="")`、`GmDecision(intent_summary="", checks=[], proactive_npc_triggers=[], scene_transition=None, memory_queries=[])`、`NpcReaction(npc_id, speech, action=None)`、`parse_decision_json(raw: str) -> GmDecision`（容忍 markdown 围栏与前后噪声）
  - `narrative.py`：`Segment(speaker, text)`、`MARKER_RE`、`parse_segments(text) -> list[Segment]`（`[[npc:<id>]]...[[/npc]]` → 有序段落；纯文本 → 单个 `gm` 段；空文本 → `[]`）

- [ ] **Step 1: 写 conftest 公共 fixture**

`backend/tests/conftest.py`：
```python
import pytest

from app.content.schema import Module

MINI_MODULE_DICT = {
    "meta": {"id": "mini", "title": "迷你模组"},
    "opening": {"narration": "开场叙述", "scene_id": "gate"},
    "scenes": [
        {"id": "gate", "name": "村口", "npcs": ["guard"], "exits": ["tavern"]},
        {"id": "tavern", "name": "酒馆", "npcs": ["barkeep"], "exits": []},
    ],
    "npcs": [
        {"id": "guard", "name": "王守卫", "persona": "多疑的老兵", "initial_attitude": 40},
        {"id": "barkeep", "name": "刘老板", "persona": "健谈的酒馆老板", "initial_attitude": 60},
    ],
    "clues": [],
    "endings": [{"id": "e1", "scene": "tavern", "condition": "揭开真相"}],
}

@pytest.fixture
def mini_module() -> Module:
    return Module.model_validate(MINI_MODULE_DICT)

@pytest.fixture
def repo(tmp_path):
    from app.storage.db import init_db, make_engine
    from app.storage.repo import SqliteRepository
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(engine)
    return SqliteRepository(engine)

@pytest.fixture
def campaign(repo):
    return repo.create_campaign("mini", "测试局")
```

- [ ] **Step 2: 写失败测试**

`backend/tests/graph/test_state.py`：
```python
from app.graph.state import merge_dict, TurnInput, TurnInputs

def test_merge_dict_merges_and_clears():
    assert merge_dict({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert merge_dict({"a": 1}, {}) == {}

def test_turn_inputs_roundtrip():
    ti = TurnInputs(turn_id=1, inputs=[TurnInput("p1", "pc_1", "我推门进去")], skipped=["p2"])
    data = ti.model_dump()
    assert data["inputs"][0]["text"] == "我推门进去" and data["skipped"] == ["p2"]
```

`backend/tests/graph/test_schemas.py`：
```python
import pytest
from app.graph.schemas import GmDecision, parse_decision_json

def test_parse_plain_json():
    d = parse_decision_json('{"intent_summary": "查看四周"}')
    assert d.intent_summary == "查看四周" and d.checks == []

def test_parse_fenced_json_with_noise():
    raw = '好的，裁决如下：\n```json\n{"intent_summary": "潜入", "checks": [{"actor": "pc_1", "skill": "潜行", "difficulty": "hard"}]}\n```\n完毕。'
    d = parse_decision_json(raw)
    assert d.checks[0].skill == "潜行" and d.checks[0].difficulty == "hard"

def test_parse_rejects_garbage():
    with pytest.raises(Exception):
        parse_decision_json("这里没有 JSON")
```

`backend/tests/graph/test_narrative.py`：
```python
from app.graph.narrative import parse_segments

def test_plain_text_is_single_gm_segment():
    segs = parse_segments("你推开门，灰尘扑面而来。")
    assert len(segs) == 1 and segs[0].speaker == "gm"

def test_marker_produces_ordered_segments():
    text = "你推开门。[[npc:guard]]站住！[[/npc]]他的眼神充满怀疑。"
    segs = parse_segments(text)
    assert [s.speaker for s in segs] == ["gm", "npc:guard", "gm"]
    assert segs[1].text == "站住！"

def test_multiple_npc_markers_and_empty_text():
    segs = parse_segments("[[npc:a]]一[[/npc]]中间[[npc:b]]二[[/npc]]")
    assert [s.speaker for s in segs] == ["npc:a", "gm", "npc:b"]
    assert parse_segments("   ") == []
```

- [ ] **Step 3: 验证失败**

Run: `cd backend; uv run pytest tests/graph -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.graph.state'`

- [ ] **Step 4: 实现 state.py**

`backend/app/graph/state.py`：
```python
"""主图状态：L1 图内状态 + 回合中间产物。"""
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field


class TurnInput(BaseModel):
    player_id: str
    character_id: str
    text: str
    submitted_at: str = ""


class TurnInputs(BaseModel):
    turn_id: int
    inputs: list[TurnInput] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


def merge_dict(current: dict, update: dict) -> dict:
    """dict 通道合并；update 为空 dict 时清空（回合间重置用）。"""
    if update == {}:
        return {}
    return {**current, **update}


class GameState(TypedDict, total=False):
    campaign_id: str
    branch_id: str
    thread_id: str
    turn_id: int
    is_opening: bool
    # L2 快照（intake 装载，回合内只读）
    scene_id: str
    npc_attitudes: dict[str, int]
    characters: dict[str, dict]
    # 预算层级（ok / tight / exceeded / paused）
    budget_level: str
    # 本回合产物
    player_inputs: list[dict]
    decision: dict | None
    decision_raw: str
    check_results: list[dict]
    memory_context: str
    npc_reactions: Annotated[dict[str, dict], merge_dict]
    narration: str
    narration_segments: list[dict]
    error: str | None
    degraded: Annotated[dict[str, bool], merge_dict]
```

- [ ] **Step 5: 实现 schemas.py**

`backend/app/graph/schemas.py`：
```python
"""GM 决策与 NPC 反应的结构化契约；叙事有序性依赖它保持中间产物结构化。"""
from pydantic import BaseModel, Field

from app.rules.check import CheckDifficulty


class CheckRequest(BaseModel):
    actor: str
    skill: str
    difficulty: CheckDifficulty = CheckDifficulty.REGULAR


class NpcTrigger(BaseModel):
    npc_id: str
    trigger: str = ""


class SceneTransition(BaseModel):
    to_scene: str
    reason: str = ""


class GmDecision(BaseModel):
    intent_summary: str = ""
    checks: list[CheckRequest] = Field(default_factory=list)
    proactive_npc_triggers: list[NpcTrigger] = Field(default_factory=list)
    scene_transition: SceneTransition | None = None
    memory_queries: list[str] = Field(default_factory=list)


class NpcReaction(BaseModel):
    npc_id: str
    speech: str
    action: str | None = None


def parse_decision_json(raw: str) -> GmDecision:
    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in LLM output")
    return GmDecision.model_validate_json(text[start:end + 1])
```

- [ ] **Step 6: 实现 narrative.py**

`backend/app/graph/narrative.py`：
```python
"""叙事分段：NPC 台词不独立外发，由 GM 统一编排后用标记表达说话人。"""
import re
from dataclasses import dataclass

MARKER_RE = re.compile(r"\[\[npc:([A-Za-z0-9_\-]+)\]\]\s*(.*?)\s*\[\[/npc\]\]", re.S)


@dataclass(frozen=True)
class Segment:
    speaker: str  # "gm" 或 f"npc:{npc_id}"
    text: str


def parse_segments(text: str) -> list[Segment]:
    segments: list[Segment] = []
    pos = 0
    for m in MARKER_RE.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            segments.append(Segment("gm", before))
        segments.append(Segment(f"npc:{m.group(1)}", m.group(2).strip()))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        segments.append(Segment("gm", tail))
    if not segments and text.strip():
        segments.append(Segment("gm", text.strip()))
    return segments
```

- [ ] **Step 7: 验证通过**

Run: `cd backend; uv run pytest tests/graph -q`
Expected: PASS（8 passed）

- [ ] **Step 8: Commit**

```bash
git add backend/app/graph/state.py backend/app/graph/schemas.py backend/app/graph/narrative.py backend/tests/conftest.py backend/tests/graph
git commit -m "feat(graph): game state, decision schemas, narrative segment parser"
```

---

### Task 15: 回合节点 A —— intake 与 wait_input

**Files:**
- Create: `backend/app/graph/nodes/turn.py`（本任务含 intake、wait_input；Task 16 追加）
- Test: `backend/tests/graph/test_intake.py`, `backend/tests/graph/test_wait_input.py`

**Interfaces:**
- Consumes: `GameState/TurnInputs`（Task 14）、`SqliteRepository`（Task 7/8/9）、`Module`（Task 4）、`BudgetGuard`（Task 12）
- Produces：
  - `build_intake_node(repo, module, guard) -> Callable[[GameState], dict]`
    - 装载 L2 快照（`get_state_at` / `list_characters_at`，缺省用模组初始值）；`is_opening = turn_id == 0 且无输入`
    - 预算检查点①（回合开始）：写 `budget_level`；PAUSED 时同时写 `error="budget_paused"`（L4 熔断，不推进）
    - 写 `turn_start` 事件（payload 含输入摘要）
  - `wait_input(state) -> dict`：`interrupt({"type": "await_inputs", "turn_id": ...})`；resume 后从 payload（dict，结构同 `TurnInputs.model_dump()`）取 `inputs`；返回时**清空本回合 pending**：`decision=None, check_results=[], npc_reactions={}, narration="", narration_segments=[], error=None, degraded={}, memory_context=""`，并设 `is_opening=False`

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_intake.py`：
```python
from app.config import Settings
from app.graph.nodes.turn import build_intake_node
from app.llm.usage import BudgetGuard

def make_node(repo, module, **overrides):
    guard = BudgetGuard(Settings(**overrides))
    return build_intake_node(repo, module, guard)

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 0, "player_inputs": [], **extra}

def test_opening_uses_module_defaults(repo, campaign, mini_module):
    upd = make_node(repo, mini_module)(base_state(campaign))
    assert upd["is_opening"] is True
    assert upd["scene_id"] == "gate"
    assert upd["npc_attitudes"]["guard"] == 40
    assert upd["budget_level"] == "ok" and upd["error"] is None

def test_uses_latest_l2_snapshot(repo, campaign, mini_module):
    b = campaign.active_branch_id
    repo.append_state(campaign.id, b, 2, {"scene_id": "tavern", "npc_attitudes": {"guard": 10}})
    upd = make_node(repo, mini_module)(base_state(campaign, turn_id=3, player_inputs=[{"text": "继续"}]))
    assert upd["scene_id"] == "tavern" and upd["npc_attitudes"]["guard"] == 10

def test_writes_turn_start_event(repo, campaign, mini_module):
    make_node(repo, mini_module)(base_state(campaign))
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert "turn_start" in types

def test_paused_when_campaign_cost_cap_reached(repo, campaign, mini_module):
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen-plus", 1, 1, 5.0, 100)
    upd = make_node(repo, mini_module, campaign_cost_cap_usd=1.0)(base_state(campaign))
    assert upd["budget_level"] == "paused" and upd["error"] == "budget_paused"
```

`backend/tests/graph/test_wait_input.py`：
```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph.nodes.turn import wait_input
from app.graph.state import GameState

def build_mini():
    g = StateGraph(GameState)
    g.add_node("wait_input", wait_input)
    g.add_edge(START, "wait_input")
    g.add_edge("wait_input", END)
    return g.compile(checkpointer=MemorySaver())

def test_interrupt_then_resume_clears_pending():
    app = build_mini()
    cfg = {"configurable": {"thread_id": "t1"}}
    app.invoke({"turn_id": 0, "player_inputs": [], "npc_reactions": {"old": {}},
                "check_results": [{"x": 1}], "narration": "旧叙事", "error": "旧错误"}, cfg)
    assert app.get_state(cfg).next == ("wait_input",)  # 已挂起
    result = app.invoke(Command(resume={
        "turn_id": 1,
        "inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我推门进去"}],
        "skipped": [],
    }), cfg)
    assert result["player_inputs"][0]["text"] == "我推门进去"
    assert result["is_opening"] is False
    assert result["npc_reactions"] == {} and result["check_results"] == []
    assert result["error"] is None and result["narration"] == ""
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_intake.py tests/graph/test_wait_input.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.graph.nodes.turn'`

- [ ] **Step 3: 实现**

`backend/app/graph/nodes/turn.py`：
```python
"""回合节点：intake / wait_input（本任务）与 resolve_checks / post_turn / fallback（Task 16）。"""
from langgraph.types import interrupt

from app.graph.state import GameState


def build_intake_node(repo, module, guard):
    def intake(state: GameState) -> dict:
        campaign_id = state["campaign_id"]
        branch_id = state["branch_id"]
        turn_id = state["turn_id"]
        snap = repo.get_state_at(campaign_id, branch_id, turn_id) or {}
        scene_id = snap.get("scene_id", module.opening.scene_id)
        attitudes = snap.get("npc_attitudes") or {n.id: n.initial_attitude for n in module.npcs}
        chars = {c["id"]: c for c in repo.list_characters_at(campaign_id, branch_id, turn_id)}
        inputs = state.get("player_inputs", [])
        is_opening = turn_id == 0 and not inputs

        turn_tokens = repo.turn_token_total(campaign_id, branch_id, turn_id)
        cost = repo.campaign_cost_total(campaign_id)
        level = str(guard.check(turn_tokens, cost))

        repo.add_event(campaign_id, branch_id, turn_id, type="turn_start",
                       payload={"inputs": [i.get("text", "") for i in inputs],
                                "is_opening": is_opening, "budget_level": level})

        upd: dict = {"scene_id": scene_id, "npc_attitudes": attitudes, "characters": chars,
                     "is_opening": is_opening, "budget_level": level, "error": None}
        if level == "paused":
            upd["error"] = "budget_paused"
        return upd

    return intake


def wait_input(state: GameState) -> dict:
    payload = interrupt({"type": "await_inputs", "turn_id": state.get("turn_id", 0)})
    inputs = payload.get("inputs", []) if isinstance(payload, dict) else []
    return {
        "player_inputs": inputs,
        "is_opening": False,
        # 清空本回合 pending（与"失败不推进/读档重掷"语义一致）
        "decision": None,
        "decision_raw": "",
        "check_results": [],
        "npc_reactions": {},
        "narration": "",
        "narration_segments": [],
        "memory_context": "",
        "error": None,
        "degraded": {},
    }
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/graph -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/turn.py backend/tests/graph/test_intake.py backend/tests/graph/test_wait_input.py
git commit -m "feat(graph): intake and wait_input nodes with interrupt/resume"
```

---

### Task 16: 回合节点 B —— resolve_checks、post_turn、fallback

**Files:**
- Modify: `backend/app/graph/nodes/turn.py`（追加节点）
- Test: `backend/tests/graph/test_resolve_checks.py`, `backend/tests/graph/test_post_turn.py`

**Interfaces:**
- Consumes: `roll_check/new_seed`（Task 2/3）、`SqliteRepository`（Task 9）、`JournalMemory`（Task 13）
- Produces（追加到 `turn.py`）：
  - `build_resolve_checks_node(repo) -> Callable`：对 `state["decision"]["checks"]` 逐条掷骰，写 DiceRecord（含 seed）+ `check` 事件；返回 `{"check_results": [{actor, skill, roll, skill_value, level, success, seed, difficulty}]}`
  - `_skill_value(state, character_id, skill) -> int`：从 `state["characters"]` 查技能值（技能表 → 属性表 → 0）
  - `build_post_turn_node(repo, memory) -> Callable`：写 `narration` 事件（含 segments）、`append_state` 快照（scene_id + npc_attitudes）、`memory.update_summaries`；返回 `{"turn_id": turn_id + 1, "decision": None}`
  - `fallback(state) -> dict`：清空 pending（`player_inputs=[]`、`decision=None`、`check_results=[]`、`npc_reactions={}`、`narration=""`、`narration_segments=[]`、`degraded={}`），保留 `error`

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_resolve_checks.py`：
```python
import pytest
from app.graph.nodes.turn import build_resolve_checks_node

@pytest.fixture
def node(repo, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.turn.new_seed", lambda: 123)
    return build_resolve_checks_node(repo)

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "characters": {"pc_1": {"id": "pc_1", "skills": {"侦查": 50},
                                                  "attributes": {"力量": 60}}},
            "decision": {"checks": [{"actor": "pc_1", "skill": "侦查", "difficulty": "regular"},
                                    {"actor": "pc_1", "skill": "力量", "difficulty": "hard"}]},
            **extra}

def test_rolls_each_check_persists_dice_and_events(node, repo, campaign):
    upd = node(base_state(campaign))
    results = upd["check_results"]
    assert len(results) == 2
    assert results[0]["actor"] == "pc_1" and 1 <= results[0]["roll"] <= 100
    assert all(r["seed"] == 123 for r in results)
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert len(rows) == 2 and rows[0].seed == 123
    assert len(repo.list_events(campaign.id, campaign.active_branch_id, types=["check"])) == 2

def test_no_checks_returns_empty(node, campaign):
    upd = node(base_state(campaign, decision={"checks": []}))
    assert upd["check_results"] == []

def test_missing_character_yields_zero_skill(node, repo, campaign):
    upd = node(base_state(campaign, decision={"checks": [{"actor": "ghost", "skill": "侦查"}]},
                          characters={}))
    assert upd["check_results"][0]["skill_value"] == 0
```

`backend/tests/graph/test_post_turn.py`：
```python
import json
from app.graph.nodes.turn import build_post_turn_node, fallback

class SpyMemory:
    def __init__(self):
        self.calls = []
    def update_summaries(self, campaign_id, branch_id, turn_id):
        self.calls.append((campaign_id, branch_id, turn_id))

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 2, "scene_id": "tavern", "npc_attitudes": {"guard": 35},
            "narration": "你走进酒馆。[[npc:barkeep]]欢迎光临！[[/npc]]",
            "narration_segments": [{"speaker": "gm", "text": "你走进酒馆。"},
                                   {"speaker": "npc:barkeep", "text": "欢迎光临！"}],
            **extra}

def test_post_turn_persists_and_advances(repo, campaign):
    mem = SpyMemory()
    upd = build_post_turn_node(repo, mem)(base_state(campaign))
    assert upd["turn_id"] == 3 and upd["decision"] is None
    assert mem.calls == [(campaign.id, campaign.active_branch_id, 2)]
    snap = repo.get_state_at(campaign.id, campaign.active_branch_id, 2)
    assert snap["scene_id"] == "tavern" and snap["npc_attitudes"]["guard"] == 35
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["narration"])
    assert len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert payload["segments"][1]["speaker"] == "npc:barkeep"

def test_fallback_clears_pending_keeps_error():
    upd = fallback({"error": "decision_invalid", "npc_reactions": {"a": {}}, "narration": "x"})
    assert upd["error"] == "decision_invalid"  # error 保留（调用方读取后由 wait_input 清除）
    assert upd["npc_reactions"] == {} and upd["narration"] == "" and upd["check_results"] == []
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_resolve_checks.py tests/graph/test_post_turn.py -q`
Expected: FAIL —— `AttributeError: module 'app.graph.nodes.turn' has no attribute 'build_resolve_checks_node'`

- [ ] **Step 3: 实现（追加到 turn.py，并在头部补充 import）**

头部 import 更新为：
```python
from langgraph.types import interrupt

from app.graph.state import GameState
from app.rules.check import CheckDifficulty, roll_check
from app.rules.dice import new_seed
```

追加实现：
```python
def _skill_value(state: GameState, character_id: str, skill: str) -> int:
    char = state.get("characters", {}).get(character_id)
    if not char:
        return 0
    return char.get("skills", {}).get(skill, char.get("attributes", {}).get(skill, 0))


def build_resolve_checks_node(repo):
    def resolve_checks(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        checks = (state.get("decision") or {}).get("checks", [])
        results = []
        for chk in checks:
            actor, skill = chk["actor"], chk["skill"]
            skill_value = _skill_value(state, actor, skill)
            seed = new_seed()
            r = roll_check(actor, skill, skill_value,
                           CheckDifficulty(chk.get("difficulty", "regular")), seed)
            repo.add_dice_record(campaign_id, branch_id, turn_id, r.actor, r.skill,
                                 r.skill_value, str(r.difficulty), r.roll, str(r.level), r.seed)
            verdict = "成功" if r.success else "失败"
            repo.add_event(campaign_id, branch_id, turn_id, type="check",
                           payload={"text": f"{actor} 的「{skill}」检定：{r.roll}/{r.skill_value} "
                                            f"→ {r.level}（{verdict}）",
                                    "roll": r.roll, "level": str(r.level), "success": r.success})
            results.append({"actor": r.actor, "skill": r.skill, "roll": r.roll,
                            "skill_value": r.skill_value, "level": str(r.level),
                            "success": r.success, "seed": r.seed})
        return {"check_results": results}

    return resolve_checks


def build_post_turn_node(repo, memory):
    def post_turn(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        narration = state.get("narration", "")
        if narration:
            repo.add_event(campaign_id, branch_id, turn_id, type="narration",
                           payload={"text": narration,
                                    "segments": state.get("narration_segments", [])})
        repo.append_state(campaign_id, branch_id, turn_id,
                          {"scene_id": state.get("scene_id"),
                           "npc_attitudes": state.get("npc_attitudes", {})})
        memory.update_summaries(campaign_id, branch_id, turn_id)
        return {"turn_id": turn_id + 1, "decision": None}

    return post_turn


def fallback(state: GameState) -> dict:
    """失败不推进：清空本轮 pending，保留 error 供调用方读取（wait_input 恢复时清除）。"""
    return {"player_inputs": [], "decision": None, "decision_raw": "",
            "check_results": [], "npc_reactions": {}, "narration": "",
            "narration_segments": [], "degraded": {}}
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/graph -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/turn.py backend/tests/graph/test_resolve_checks.py backend/tests/graph/test_post_turn.py
git commit -m "feat(graph): resolve_checks, post_turn, fallback nodes"
```

---

### Task 17: GM 节点 —— gm_decide 与 validate_decision（repair 重试）

**Files:**
- Create: `backend/app/graph/nodes/gm.py`
- Test: `backend/tests/graph/test_gm_decide.py`

**Interfaces:**
- Consumes: `LLMClient`（Task 11）、`GmDecision/parse_decision_json`（Task 14）、`Module`
- Produces：
  - `DECIDE_SYSTEM`（提示词常量）；`build_decide_node(client, module) -> Callable`
    - 组装上下文：场景名/描述、在场 NPC（名+人设+当前态度）、记忆上下文、玩家行动（开场回合为"（本回合为开场，无玩家行动）"）
    - `budget_level == "exceeded"` 时 `cheap=True`（熔断阶梯③：GM 换便宜模型）
    - 返回 `{"decision_raw": raw}`
  - `build_validate_node(client) -> Callable`
    - `parse_decision_json` 成功 → `{"decision": decision.model_dump(mode="json"), "error": None}`
    - 失败 → 把解析错误反馈给模型 repair 重试 **恰好 1 次**；仍失败 → `{"error": "decision_invalid", "decision": None, "degraded": {"decision_invalid": True}}`

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_gm_decide.py`：
```python
from app.config import Pricing, PricingEntry, Settings
from app.graph.nodes.gm import build_decide_node, build_validate_node
from app.llm.client import LLMClient, LlmContext

CTX_KEYS = ("campaign_id", "branch_id", "turn_id")

def make_client(script):
    settings = Settings()
    pricing = Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })
    sink_rows = []
    built: dict = {}

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        built[model] = FakeLLM(list(script))
        return built[model]

    class Sink:
        def record_usage(self, *a, **kw):
            sink_rows.append(kw)

    return LLMClient(settings, pricing, usage_sink=Sink(), model_factory=factory), built, sink_rows

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "scene_id": "gate", "npc_attitudes": {"guard": 40},
            "player_inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我想进城"}],
            "memory_context": "前情摘要：村庄不安宁", "budget_level": "ok", **extra}

def test_decide_builds_context_and_returns_raw(campaign, mini_module):
    client, built, _ = make_client(['{"intent_summary": "进城"}'])
    upd = build_decide_node(client, mini_module)(base_state(campaign))
    assert upd["decision_raw"] == '{"intent_summary": "进城"}'
    prompt = built["qwen-plus"].calls[0][1].content
    assert "村口" in prompt and "我想进城" in prompt and "王守卫" in prompt and "前情摘要" in prompt

def test_decide_switches_to_cheap_model_when_exceeded(campaign, mini_module):
    client, built, rows = make_client(['{"intent_summary": "x"}'])
    build_decide_node(client, mini_module)(base_state(campaign, budget_level="exceeded"))
    assert "qwen-turbo" in built and rows[0]["model"] == "qwen-turbo"

def test_validate_parses_fenced_output(campaign):
    client, _, _ = make_client([])
    raw = '```json\n{"intent_summary": "潜入", "checks": [{"actor": "pc_1", "skill": "潜行", "difficulty": "hard"}]}\n```'
    upd = build_validate_node(client)({"decision_raw": raw, "budget_level": "ok"})
    assert upd["decision"]["checks"][0]["skill"] == "潜行" and upd["error"] is None

def test_validate_repairs_once_then_succeeds(campaign):
    client, built, _ = make_client(['{"intent_summary": "修复后的合法输出"}'])
    state = {"decision_raw": "这不是 JSON", "budget_level": "ok",
             "campaign_id": "c", "branch_id": "c@main", "turn_id": 1}
    upd = build_validate_node(client)(state)
    assert upd["decision"]["intent_summary"] == "修复后的合法输出"
    assert len(built["qwen-plus"].calls) == 1

def test_validate_gives_up_after_one_repair(campaign):
    client, built, _ = make_client(["还是不是 JSON"])
    state = {"decision_raw": "不是 JSON", "budget_level": "ok",
             "campaign_id": "c", "branch_id": "c@main", "turn_id": 1}
    upd = build_validate_node(client)(state)
    assert upd["error"] == "decision_invalid" and upd["decision"] is None
    assert upd["degraded"] == {"decision_invalid": True}
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_gm_decide.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.graph.nodes.gm'`

- [ ] **Step 3: 实现**

`backend/app/graph/nodes/gm.py`：
```python
"""GM 节点：结构化裁决（decide）与校验（validate，含 repair 重试）。"""
from typing import Callable

from app.graph.schemas import parse_decision_json
from app.graph.state import GameState
from app.llm.client import ChatMessage, LLMClient, LlmContext

DECIDE_SYSTEM = (
    "你是跑团主持人（COC 风格）。基于玩家行动与当前场景做结构化裁决，只输出一个 JSON 对象，字段：\n"
    'intent_summary(str)、checks(数组，元素 {"actor","skill","difficulty"(regular|hard|extreme)})、'
    'proactive_npc_triggers(数组，元素 {"npc_id","trigger"})、'
    'scene_transition(null 或 {"to_scene","reason"})、memory_queries(字符串数组)。\n'
    "规则：只为玩家的主动行动要求检定，每回合最多 2 个检定；NPC 只能用场景内列出的；"
    "开场回合可以引入场面但不要要求检定。"
)


def _ctx(state: GameState) -> LlmContext:
    return LlmContext(state["campaign_id"], state["branch_id"], state["turn_id"])


def _cheap(state: GameState) -> bool:
    return state.get("budget_level") == "exceeded"


def build_decide_node(client: LLMClient, module) -> Callable[[GameState], dict]:
    def gm_decide(state: GameState) -> dict:
        scene = module.scene(state["scene_id"])
        npc_lines = "\n".join(
            f"- {nid}: {module.npc(nid).name}（{module.npc(nid).persona}），当前态度 {state['npc_attitudes'].get(nid, 50)}"
            for nid in scene.npcs
        ) or "（无）"
        inputs_txt = "\n".join(
            f"- {i['player_id']}: {i['text']}" for i in state.get("player_inputs", [])
        ) or "（本回合为开场，无玩家行动）"
        user = (
            f"当前场景：{scene.name}\n{scene.description}\n"
            f"在场 NPC：\n{npc_lines}\n"
            f"记忆上下文：\n{state.get('memory_context') or '（无）'}\n"
            f"玩家行动：\n{inputs_txt}"
        )
        raw = client.chat("gm", [ChatMessage(role="system", content=DECIDE_SYSTEM),
                                 ChatMessage(role="user", content=user)],
                          _ctx(state), cheap=_cheap(state))
        return {"decision_raw": raw}

    return gm_decide


def build_validate_node(client: LLMClient) -> Callable[[GameState], dict]:
    def validate_decision(state: GameState) -> dict:
        raw = state.get("decision_raw", "")
        try:
            decision = parse_decision_json(raw)
        except Exception as first_error:
            repair = [ChatMessage(
                role="user",
                content=(f"你上次的输出无法解析（{first_error}）。"
                         f"请只输出合法 JSON，字段要求不变。上次输出：\n{raw}"),
            )]
            try:
                fixed = client.chat("gm", repair, _ctx(state), cheap=_cheap(state))
                decision = parse_decision_json(fixed)
            except Exception:
                return {"error": "decision_invalid", "decision": None,
                        "degraded": {"decision_invalid": True}}
        return {"decision": decision.model_dump(mode="json"), "error": None}

    return validate_decision
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/graph -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/gm.py backend/tests/graph/test_gm_decide.py
git commit -m "feat(graph): gm_decide and validate_decision with repair retry"
```
---

### Task 18: GM 节点 —— gm_narrate（叙事统一编排）

**Files:**
- Modify: `backend/app/graph/nodes/gm.py`（追加 narrate）
- Test: `backend/tests/graph/test_gm_narrate.py`

**Interfaces:**
- Consumes: `LLMClient`（Task 11）、`parse_segments`（Task 14）、`Module`（Task 4）、`GmDecision`/`_cheap`（Task 17）
- Produces：
  - `NARRATE_SYSTEM`（提示词常量，要求 NPC 台词用 `[[npc:<id>]]...[[/npc]]` 标记）
  - `build_narrate_node(client, module) -> Callable[[GameState], dict]`
    - 组装：场景（名+描述）、开场素材（`is_opening` 时嵌入 `module.opening.narration`）、玩家行动、检定结果行、NPC 反应行（**过滤沉默占位**：speech 与 action 均为空的不进提示词）
    - 成功（`parse_segments(raw)` 非空）→ `{"narration": raw, "narration_segments": [{"speaker","text"}...], "error": None}`
    - 失败（异常或空输出）→ 反馈后 repair 重试**恰好 1 次**；仍失败 → `{"error": "narrate_failed", "degraded": {"narrate_failed": True}, "narration": "", "narration_segments": []}`（规格 §8：失败不推进）
    - `budget_level == "exceeded"` 时 `cheap=True`（熔断阶梯③）

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_gm_narrate.py`：
```python
from app.config import Pricing, PricingEntry, Settings
from app.graph.nodes.gm import build_narrate_node
from app.llm.client import LLMClient

def make_client(script):
    settings = Settings()
    pricing = Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })
    built: dict = {}

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        built[model] = FakeLLM(list(script))
        return built[model]

    return LLMClient(settings, pricing, model_factory=factory), built

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "scene_id": "gate", "is_opening": False,
            "player_inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我想进城"}],
            "check_results": [{"actor": "pc_1", "skill": "侦查", "roll": 73,
                               "skill_value": 50, "level": "fail", "success": False, "seed": 1}],
            "npc_reactions": {"guard": {"npc_id": "guard", "speech": "站住！", "action": "伸手拦路"},
                              "barkeep": {"npc_id": "barkeep", "speech": "", "action": None}},
            "memory_context": "", "budget_level": "ok", **extra}

def test_narrate_returns_ordered_segments(campaign, mini_module):
    client, built = make_client(["你推开门。[[npc:guard]]站住！[[/npc]]他警惕地盯着你。"])
    upd = build_narrate_node(client, mini_module)(base_state(campaign))
    assert [s["speaker"] for s in upd["narration_segments"]] == ["gm", "npc:guard", "gm"]
    assert upd["error"] is None

def test_prompt_contains_material_and_filters_silent_npc(campaign, mini_module):
    client, built = make_client(["有效叙事。"])
    build_narrate_node(client, mini_module)(base_state(campaign))
    prompt = built["qwen-plus"].calls[0][1].content
    assert "村口" in prompt and "侦查" in prompt and "73/50" in prompt
    assert "站住！" in prompt and "王守卫" in prompt
    assert "barkeep" not in prompt  # 沉默占位被过滤

def test_empty_output_retries_once(campaign, mini_module):
    client, built = make_client(["", "补上的有效叙事。"])
    upd = build_narrate_node(client, mini_module)(base_state(campaign))
    assert upd["narration"] == "补上的有效叙事。" and upd["error"] is None
    assert len(built["qwen-plus"].calls) == 2

def test_gives_up_after_one_repair(campaign, mini_module):
    client, built = make_client(["", "   "])
    upd = build_narrate_node(client, mini_module)(base_state(campaign))
    assert upd["error"] == "narrate_failed"
    assert upd["degraded"] == {"narrate_failed": True}
    assert upd["narration"] == "" and upd["narration_segments"] == []
    assert len(built["qwen-plus"].calls) == 2

def test_opening_embeds_opening_narration(campaign, mini_module):
    client, built = make_client(["开场叙事。"])
    build_narrate_node(client, mini_module)(base_state(campaign, is_opening=True, player_inputs=[]))
    prompt = built["qwen-plus"].calls[0][1].content
    assert "开场叙述" in prompt  # mini_module.opening.narration

def test_cheap_model_when_exceeded(campaign, mini_module):
    client, built = make_client(["开场叙事。"])
    build_narrate_node(client, mini_module)(base_state(campaign, budget_level="exceeded"))
    assert "qwen-turbo" in built and "qwen-plus" not in built
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_gm_narrate.py -q`
Expected: FAIL —— `ImportError: cannot import name 'build_narrate_node' from 'app.graph.nodes.gm'`

- [ ] **Step 3: 实现（追加到 gm.py，并在头部补充 import）**

头部 import 更新为：
```python
from typing import Callable

from app.graph.narrative import parse_segments
from app.graph.schemas import parse_decision_json
from app.graph.state import GameState
from app.llm.client import ChatMessage, LLMClient, LlmContext
```

追加实现：
```python
NARRATE_SYSTEM = (
    "你是跑团主持人（COC 风格）。把本回合的结果编排成一段连贯的中文叙事。\n"
    "要求：\n"
    "1. NPC 的台词必须用标记包裹：[[npc:<npc_id>]]台词内容[[/npc]]，<npc_id> 只能用给定的 id；\n"
    "2. 标记之外的文字是你的旁白（环境、动作、结果）；\n"
    "3. 把检定结果自然地写进叙事（成功与失败都要有后果）；\n"
    "4. 不要输出 JSON、不要解释规则、不要任何元评论。"
)


def _check_lines(state: GameState) -> str:
    lines = []
    for c in state.get("check_results", []):
        verdict = "成功" if c.get("success") else "失败"
        lines.append(f"- {c['actor']} 的「{c['skill']}」：{c['roll']}/{c['skill_value']} "
                     f"→ {c['level']}（{verdict}）")
    return "\n".join(lines) or "（本回合无检定）"


def _reaction_lines(state: GameState, module) -> str:
    lines = []
    for npc_id, r in (state.get("npc_reactions") or {}).items():
        r = r or {}
        speech, action = r.get("speech", ""), r.get("action")
        if not speech and not action:
            continue  # 沉默占位（NPC 失败降级，规格 §8）：不进入提示词
        try:
            name = module.npc(npc_id).name
        except KeyError:
            name = npc_id
        part = f"- {npc_id}（{name}）"
        if speech:
            part += f" 台词：「{speech}」"
        if action:
            part += f" 动作：{action}"
        lines.append(part)
    return "\n".join(lines) or "（本回合无 NPC 回应）"


def build_narrate_node(client: LLMClient, module) -> Callable[[GameState], dict]:
    def gm_narrate(state: GameState) -> dict:
        scene = module.scene(state["scene_id"])
        inputs_txt = "\n".join(
            f"- {i['player_id']}: {i['text']}" for i in state.get("player_inputs", [])
        ) or "（开场回合，无玩家行动）"
        opening_line = ""
        if state.get("is_opening"):
            opening_line = f"开场设定（请扩写为叙事）：\n{module.opening.narration}\n"
        user = (
            f"{opening_line}"
            f"当前场景：{scene.name}\n{scene.description}\n"
            f"玩家行动：\n{inputs_txt}\n"
            f"检定结果：\n{_check_lines(state)}\n"
            f"NPC 反应：\n{_reaction_lines(state, module)}\n"
            "请输出本回合的完整叙事。"
        )
        messages = [ChatMessage(role="system", content=NARRATE_SYSTEM),
                    ChatMessage(role="user", content=user)]
        last_error = ""
        for _ in range(2):  # 首次 + repair 重试 1 次（规格 §8）
            try:
                raw = client.chat("gm", messages, _ctx(state), cheap=_cheap(state))
                segs = parse_segments(raw)
                if segs:
                    return {"narration": raw,
                            "narration_segments": [{"speaker": s.speaker, "text": s.text}
                                                   for s in segs],
                            "error": None}
                last_error = "empty narration"
            except Exception as exc:
                last_error = str(exc)
            messages = messages + [ChatMessage(
                role="user",
                content=f"上次输出不合格（{last_error}）。请重新输出完整叙事，"
                        "NPC 台词必须带 [[npc:id]] 标记。")]
        return {"error": "narrate_failed", "degraded": {"narrate_failed": True},
                "narration": "", "narration_segments": []}

    return gm_narrate
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/graph -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/gm.py backend/tests/graph/test_gm_narrate.py
git commit -m "feat(graph): gm_narrate with marker-based narrative orchestration"
```

### Task 18b: 异步后台队列 + 摘要异步化（设计：`specs/2026-09-29-async-queue-design.md`）

**背景**：`post_turn` 同步调用 `memory.update_summaries`；真接线 LLM 摘要后将阻塞回合收尾。本任务落地通用 `BackgroundQueue`（watermark 追赶语义：按 key 合并、最新票胜出、丢弃自愈），摘要为首个消费者并完成 LLM 真接线；M5 Graphiti 摄取复用同一机制，不改 M2 上层。

**Files:**
- Create: `backend/app/tasks.py`、`backend/app/memory/scheduler.py`、`backend/app/memory/summarizer.py`
- Create: `backend/tests/test_tasks.py`、`backend/tests/memory/test_scheduler.py`、`backend/tests/memory/test_summarizer.py`、`backend/tests/storage/test_db_engine.py`
- Modify: `backend/app/memory/journal.py`（summarizer 签名携带 ids）、`backend/tests/memory/test_journal.py`（2 处）、`backend/app/storage/db.py`（WAL + busy_timeout）

**Interfaces:**
- Consumes: `JournalMemory`（T13）、`LLMClient.chat(role, messages, ctx)` / `LlmContext` / `ChatMessage`（T10/T11）、`Settings.extractor_model`
- Produces:
  - `tasks.py`：`BackgroundQueue(handler: Callable[[str, Any], None], name: str = "bg")`；`submit(key, payload)`（覆盖式合并；`stop()` 后忽略）/ `start()`（daemon 线程 `ensemble-{name}`）/ `run_pending() -> int`（同步处理全部待办，测试模式）/ `flush(timeout=2.0) -> bool`（待办清空且当前任务处理完毕）/ `stop()`（跑完在队任务后退出）；处理器异常一律捕获记日志、worker 永不退出
  - `scheduler.py`：`BackgroundSummaries(inner, queue)`——`update_summaries(c,b,t)` → `queue.submit(f"{c}@{b}", (c,b,t))`；`write_event/search/get_context` 透传
  - `summarizer.py`：`LLMSummarizer(client)`；`__call__(campaign_id, branch_id, turn_id, messages) -> str`（`extractor` 角色 + `LlmContext` → usage 自动记账）
  - `journal.py` 的 `summarizer` 类型：`Callable[[str, str, int, list[ChatMessage]], str] | None`
- 说明：本任务不改任何装配（T21/T24 尚不存在）；届时按设计文档 §8：`BackgroundSummaries + LLMSummarizer + queue.start()`，退出 `flush(2.0)`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_tasks.py`：
```python
from app.tasks import BackgroundQueue


def test_run_pending_coalesces_to_latest_payload():
    calls = []
    q = BackgroundQueue(lambda key, payload: calls.append((key, payload)))
    q.submit("c@main", 1)
    q.submit("c@main", 2)
    assert q.run_pending() == 1
    assert calls == [("c@main", 2)]


def test_handler_failure_is_swallowed_and_queue_survives():
    calls = []

    def handler(key, payload):
        calls.append(payload)
        if payload == 1:
            raise RuntimeError("boom")

    q = BackgroundQueue(handler)
    q.submit("k", 1)
    assert q.run_pending() == 1
    q.submit("k", 2)
    q.run_pending()
    assert calls == [1, 2]


def test_flush_waits_for_worker_to_finish():
    done = []
    q = BackgroundQueue(lambda key, payload: done.append(payload))
    q.start()
    q.submit("k", 7)
    assert q.flush(timeout=2.0) is True
    assert done == [7]
    q.stop()


def test_stop_ignores_later_submits():
    calls = []
    q = BackgroundQueue(lambda key, payload: calls.append(payload))
    q.start()
    q.stop()
    q.submit("k", 1)
    q.run_pending()
    assert calls == []
```

`backend/tests/memory/test_scheduler.py`：
```python
from app.memory.scheduler import BackgroundSummaries
from app.tasks import BackgroundQueue


class FakeMemory:
    def __init__(self):
        self.updates = []

    def update_summaries(self, campaign_id, branch_id, turn_id):
        self.updates.append((campaign_id, branch_id, turn_id))

    def write_event(self, campaign_id, branch_id, event):
        return ("write", campaign_id)

    def search(self, campaign_id, branch_id, query, limit=5):
        return [("search", query, limit)]

    def get_context(self, campaign_id, branch_id, budget_chars=1200):
        return f"ctx:{budget_chars}"


def test_update_summaries_deferred_and_coalesced():
    inner = FakeMemory()
    q = BackgroundQueue(lambda key, payload: inner.update_summaries(*payload))
    bg = BackgroundSummaries(inner, q)
    bg.update_summaries("c", "c@main", 3)
    bg.update_summaries("c", "c@main", 5)
    assert inner.updates == []                     # 主线程零执行
    q.run_pending()
    assert inner.updates == [("c", "c@main", 5)]   # 合并为最大 watermark


def test_other_methods_delegate_to_inner():
    inner = FakeMemory()
    bg = BackgroundSummaries(inner, BackgroundQueue(lambda k, p: None))
    assert bg.get_context("c", "b") == "ctx:1200"
    assert bg.search("c", "b", "磨坊") == [("search", "磨坊", 5)]
    assert bg.write_event("c", "b", object()) == ("write", "c")
```

`backend/tests/memory/test_summarizer.py`：
```python
from app.config import Pricing, PricingEntry, Settings
from app.llm.client import ChatMessage, LLMClient
from app.llm.fakes import FakeLLM
from app.memory.summarizer import LLMSummarizer


class Sink:
    def __init__(self):
        self.rows = []

    def record_usage(self, campaign_id, branch_id, turn_id, role, model, tokens_in,
                     tokens_out, cost_usd, latency_ms):
        self.rows.append((campaign_id, branch_id, turn_id, role, model))


def test_uses_extractor_role_and_records_usage():
    settings = Settings(extractor_model="qwen-turbo")
    pricing = Pricing(models={"qwen-turbo": PricingEntry(input_per_1k=0.1, output_per_1k=0.2)})
    built = {}

    def factory(model, base_url, api_key):
        if model not in built:
            built[model] = FakeLLM(["压缩后的摘要"])
        return built[model]

    sink = Sink()
    client = LLMClient(settings, pricing, usage_sink=sink, model_factory=factory)
    result = LLMSummarizer(client)("c1", "c1@main", 7,
                                   [ChatMessage(role="user", content="事件")])
    assert result == "压缩后的摘要"
    assert "qwen-turbo" in built                        # extractor 路由
    assert built["qwen-turbo"].calls[0][0].content == "事件"
    assert sink.rows == [("c1", "c1@main", 7, "extractor", "qwen-turbo")]
```

`backend/tests/storage/test_db_engine.py`：
```python
from app.storage.db import make_engine


def test_engine_enables_wal_and_busy_timeout(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
```

`backend/tests/memory/test_journal.py` 两处改签名（并断言 ids 透传）：
```python
    seen = []
    def summarizer(campaign_id, branch_id, turn_id, messages):
        calls.append(messages)
        seen.append((campaign_id, branch_id, turn_id))
        return "压缩后的摘要"
    # ...
    assert seen == [(campaign.id, b, 3)]
```
第二处（prior 摘要测试）仅函数签名改为 `(campaign_id, branch_id, turn_id, messages)`。

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/test_tasks.py tests/memory/test_scheduler.py tests/memory/test_summarizer.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.tasks'`

- [ ] **Step 3: 实现 `app/tasks.py`**

```python
"""通用后台队列：watermark 追赶语义（按 key 合并，最新票胜出）。

任务 = (key, watermark)，处理器语义为"把 key 追赶到 watermark"且必须可从持久层重算；
因此合并、丢弃、重启丢失均无害，下次提交自动补齐（设计：specs/2026-09-29-async-queue-design.md）。
"""
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class BackgroundQueue:
    """单 daemon 工作线程 + 覆盖式合并；不 start() 时用 run_pending() 同步执行（测试）。"""

    def __init__(self, handler: Callable[[str, Any], None], name: str = "bg"):
        self._handler = handler
        self._name = name
        self._pending: dict[str, Any] = {}
        self._busy = False
        self._stopping = False
        self._lock = threading.Condition()
        self._thread: threading.Thread | None = None

    def submit(self, key: str, payload: Any) -> None:
        with self._lock:
            if self._stopping:
                return
            self._pending[key] = payload
            self._lock.notify()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop,
                                        name=f"ensemble-{self._name}", daemon=True)
        self._thread.start()

    def run_pending(self) -> int:
        processed = 0
        while True:
            job = self._pop()
            if job is None:
                return processed
            self._handle(*job)
            processed += 1

    def flush(self, timeout: float = 2.0) -> bool:
        with self._lock:
            return self._lock.wait_for(lambda: not self._pending and not self._busy,
                                       timeout=timeout)

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            self._lock.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    # ---------- 内部 ----------

    def _loop(self) -> None:
        while True:
            with self._lock:
                self._lock.wait_for(lambda: self._pending or self._stopping)
                if not self._pending:
                    return  # 停止且已排空
                key, payload = self._pop_locked()
            self._handle(key, payload)

    def _pop(self) -> tuple[str, Any] | None:
        with self._lock:
            if not self._pending:
                return None
            return self._pop_locked()

    def _pop_locked(self) -> tuple[str, Any]:
        key = next(iter(self._pending))
        return key, self._pending.pop(key)

    def _handle(self, key: str, payload: Any) -> None:
        with self._lock:
            self._busy = True
        try:
            self._handler(key, payload)
        except Exception:
            logger.exception("后台任务失败（key=%s，已丢弃，等待下次提交自愈）", key)
        finally:
            with self._lock:
                self._busy = False
                self._lock.notify_all()
```

- [ ] **Step 4: 验证通过（队列单测）**

Run: `cd backend; uv run pytest tests/test_tasks.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 实现 scheduler / summarizer / journal 签名 / db pragma**

`backend/app/memory/scheduler.py`：
```python
"""摘要异步化适配器：update_summaries 变为 watermark 追赶任务；其余方法透传。"""
from typing import TYPE_CHECKING

from app.memory.base import MemoryEvent
from app.tasks import BackgroundQueue

if TYPE_CHECKING:
    from app.memory.journal import JournalMemory


class BackgroundSummaries:
    def __init__(self, inner: "JournalMemory", queue: BackgroundQueue):
        self._inner = inner
        self._queue = queue

    def update_summaries(self, campaign_id: str, branch_id: str, turn_id: int) -> None:
        self._queue.submit(f"{campaign_id}@{branch_id}", (campaign_id, branch_id, turn_id))

    def write_event(self, campaign_id: str, branch_id: str, event: MemoryEvent) -> None:
        return self._inner.write_event(campaign_id, branch_id, event)

    def search(self, campaign_id: str, branch_id: str, query: str, limit: int = 5):
        return self._inner.search(campaign_id, branch_id, query, limit=limit)

    def get_context(self, campaign_id: str, branch_id: str, budget_chars: int = 1200) -> str:
        return self._inner.get_context(campaign_id, branch_id, budget_chars=budget_chars)
```

`backend/app/memory/summarizer.py`：
```python
"""LLM 摘要器：把 JournalMemory 的 summarizer 钩子接到 LLMClient（extractor 角色 + 记账）。"""
from app.llm.client import ChatMessage, LLMClient, LlmContext


class LLMSummarizer:
    def __init__(self, client: LLMClient):
        self._client = client

    def __call__(self, campaign_id: str, branch_id: str, turn_id: int,
                 messages: list[ChatMessage]) -> str:
        return self._client.chat(
            "extractor", messages,
            LlmContext(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id))
```

`backend/app/memory/journal.py`（签名与调用处）：
```python
    def __init__(self, repo, summarizer: Callable[[str, str, int, list[ChatMessage]], str] | None = None):
        ...
    # update_summaries 内：
            content = self._summarizer(campaign_id, branch_id, turn_id, [
                ChatMessage(role="system", content=_SUMMARY_PROMPT),
                ChatMessage(role="user", content=f"{prior}新事件：\n{body}"),
            ])
```

`backend/app/storage/db.py`（WAL + busy_timeout）：
```python
from sqlalchemy import create_engine, event


def make_engine(sqlite_path: str) -> Engine:
    engine = create_engine(f"sqlite:///{sqlite_path}",
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine
```

- [ ] **Step 6: 验证通过（全量）**

Run: `cd backend; uv run pytest -q`
Expected: PASS（93 = 85 既有 + 8 新增；journal 2 处签名适配后语义不变）

- [ ] **Step 7: Commit**

```bash
git add backend/app/tasks.py backend/app/memory/scheduler.py backend/app/memory/summarizer.py backend/app/memory/journal.py backend/app/storage/db.py backend/tests/test_tasks.py backend/tests/memory/test_scheduler.py backend/tests/memory/test_summarizer.py backend/tests/memory/test_journal.py backend/tests/storage/test_db_engine.py
git commit -m "feat(memory): Task 18b async summary queue with LLM summarizer wiring"
```

---

### Task 19: NPC 子图 —— 人设组装、独立说话节点、Send 扇出分发

**Files:**
- Create: `backend/app/graph/npc.py`
- Test: `backend/tests/graph/test_npc.py`

**设计说明（实现选择，属规格 6.3 `npc.py（子图）` 的落地方式）**：NPC agent 以**独立 StateGraph 子图**实现（独立状态 schema `NpcTaskState`，`assemble → speak` 两节点）；主图侧由**普通函数 worker** 作为 Send 扇出目标，worker 内调用子图并把结果适配回主图 `npc_reactions` 通道。理由：Send 的 payload 直达普通节点函数是 LangGraph 最稳定的 map-reduce 模式，避免子图间状态 schema 映射的版本差异；功能契约（Send 并行、独立上下文、独立模型路由、结构化反应）与规格完全一致。

**Interfaces:**
- Consumes: `LLMClient`（Task 11）、`GameState`（Task 14）、`Module`（Task 4）
- Produces：
  - `NPC_SYSTEM`（提示词常量）
  - `NpcTaskState(TypedDict, total=False)`：输入 `npc_id, trigger, campaign_id, branch_id, turn_id, scene_name, scene_description, npc_name, npc_persona, npc_attitude, memory_context, player_inputs, check_results`；中间 `messages: list[dict]`（plain dict，保证可序列化）；输出 `reaction: dict`
  - `assemble_persona(task) -> dict`（纯函数：人设 + 动态态度 + 场景 + 记忆 + 检定 + 玩家行动 + 触发原因 → `{"messages": [...]}`）
  - `build_speak_node(client) -> Callable`：解析 `{"speech","action"}` JSON（容忍围栏）；解析失败**抛异常**（由 worker 兜底）
  - `build_npc_subgraph(client) -> CompiledStateGraph`（`START → assemble → speak → END`）
  - `build_npc_worker(subgraph) -> Callable[[dict], dict]`：Send 目标；成功 → `{"npc_reactions": {npc_id: reaction}}`；**任何异常 → 沉默占位** `{"npc_id": npc_id, "speech": "", "action": None}`（规格 §8：该 NPC 沉默，其余正常）
  - `build_npc_dispatch(module) -> Callable[[GameState], list[Send] | str]`（扇出规则**写死**）：
    1. 候选 = `decision.proactive_npc_triggers` 中**存在**于模组的 npc_id（保序去重）
    2. 候选为空时回退：玩家输入文本中包含场景内某 NPC 的 `name` → 该 NPC（取模组顺序第一个）
    3. `budget_level in ("tight", "exceeded")` → 候选截取前 1（阶梯②）；否则截取前 2（防并行爆炸）
    4. 无候选 → 返回字符串 `"gm_narrate"`；否则返回 `[Send("npc_respond", task), ...]`

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_npc.py`：
```python
from app.config import Pricing, PricingEntry, Settings
from app.graph.npc import (assemble_persona, build_npc_dispatch, build_npc_subgraph,
                           build_npc_worker)
from app.llm.client import LLMClient

def make_client(script):
    settings = Settings()
    pricing = Pricing(models={
        "deepseek-chat": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011)})
    built: dict = {}

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        built[model] = FakeLLM(list(script))
        return built[model]

    return LLMClient(settings, pricing, model_factory=factory), built

def task_dict(**extra):
    base = {"npc_id": "guard", "trigger": "玩家翻墙被巡逻队看到", "campaign_id": "c1",
            "branch_id": "c1@main", "turn_id": 1, "scene_name": "村口",
            "scene_description": "雾很重", "npc_name": "王守卫", "npc_persona": "多疑的老兵",
            "npc_attitude": 40, "memory_context": "玩家曾被警告过",
            "player_inputs": [{"player_id": "p1", "text": "我想进城"}],
            "check_results": [{"skill": "潜行", "roll": 30, "skill_value": 50, "success": True}]}
    return {**base, **extra}

def state_dict(**extra):
    return {"campaign_id": "c1", "branch_id": "c1@main", "turn_id": 1,
            "scene_id": "gate", "npc_attitudes": {"guard": 40, "barkeep": 60},
            "player_inputs": [], "check_results": [], "memory_context": "",
            "budget_level": "ok", **extra}

def test_assemble_persona_contains_context():
    out = assemble_persona(task_dict())
    system, user = out["messages"][0]["content"], out["messages"][1]["content"]
    assert "王守卫" in system and "多疑的老兵" in system and "40" in system
    assert "潜行" in system and "玩家曾被警告过" in system
    assert "我想进城" in user and "玩家翻墙被巡逻队看到" in user

def test_subgraph_parses_fenced_reaction():
    client, built = make_client(['```json\n{"speech": "站住！", "action": "伸手拦路"}\n```'])
    final = build_npc_subgraph(client).invoke(task_dict())
    assert final["reaction"] == {"npc_id": "guard", "speech": "站住！", "action": "伸手拦路"}
    assert "deepseek-chat" in built

def test_worker_silent_when_parse_fails():
    client, _ = make_client(["这里没有 JSON"])
    worker = build_npc_worker(build_npc_subgraph(client))
    out = worker(task_dict())
    assert out["npc_reactions"]["guard"]["speech"] == ""

def test_worker_silent_when_llm_raises():
    client, _ = make_client([])  # FakeLLM 脚本耗尽 → IndexError
    worker = build_npc_worker(build_npc_subgraph(client))
    out = worker(task_dict())
    assert out["npc_reactions"] == {"guard": {"npc_id": "guard", "speech": "", "action": None}}

def test_dispatch_dedups_and_filters_unknown(mini_module):
    d = build_npc_dispatch(mini_module)
    state = state_dict(decision={"proactive_npc_triggers": [
        {"npc_id": "guard", "trigger": "t1"}, {"npc_id": "guard"}, {"npc_id": "ghost"},
        {"npc_id": "barkeep", "trigger": "t2"}]})
    sends = d(state)
    assert [s.arg["npc_id"] for s in sends] == ["guard", "barkeep"]
    assert sends[0].arg["npc_name"] == "王守卫" and sends[0].arg["trigger"] == "t1"

def test_dispatch_tight_keeps_first_only(mini_module):
    d = build_npc_dispatch(mini_module)
    state = state_dict(budget_level="tight", decision={"proactive_npc_triggers": [
        {"npc_id": "guard"}, {"npc_id": "barkeep"}]})
    assert [s.arg["npc_id"] for s in d(state)] == ["guard"]

def test_dispatch_name_mention_fallback(mini_module):
    d = build_npc_dispatch(mini_module)
    state = state_dict(decision={},
                       player_inputs=[{"player_id": "p1", "text": "我问王守卫，到底发生了什么"}])
    assert [s.arg["npc_id"] for s in d(state)] == ["guard"]

def test_dispatch_no_candidates_returns_narrate(mini_module):
    d = build_npc_dispatch(mini_module)
    assert d(state_dict(decision={})) == "gm_narrate"
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_npc.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.graph.npc'`

- [ ] **Step 3: 实现**

`backend/app/graph/npc.py`：
```python
"""NPC 子图：每个 NPC 是独立 agent（独立上下文 / 独立模型路由 / Send 并行）。

子图拥有独立状态 schema（NpcTaskState）；主图侧以 worker 函数作为 Send 目标，
把子图结果适配回主图的 npc_reactions 通道（map-reduce，规格 6.3 / 4.1）。
"""
import json
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.graph.state import GameState
from app.llm.client import ChatMessage, LLMClient, LlmContext

NPC_SYSTEM = (
    "你是一位跑团（TRPG）中的 NPC，只以你的身份说话和行动。\n"
    '只输出一个 JSON 对象：{"speech": "你要说的台词", "action": "动作描述或 null"}。\n'
    "台词要符合你的人设与当前态度；不要替玩家做决定；不要输出其他内容。"
)


class NpcTaskState(TypedDict, total=False):
    # 输入（由主图 dispatch 组装）
    npc_id: str
    trigger: str
    campaign_id: str
    branch_id: str
    turn_id: int
    scene_name: str
    scene_description: str
    npc_name: str
    npc_persona: str
    npc_attitude: int
    memory_context: str
    player_inputs: list[dict]
    check_results: list[dict]
    # 中间产物（plain dict，保证可序列化）
    messages: list[dict]
    # 输出
    reaction: dict


def assemble_persona(task: NpcTaskState) -> dict:
    checks = "\n".join(
        f"- {c.get('skill')}：{c.get('roll')}/{c.get('skill_value')}"
        f"（{'成功' if c.get('success') else '失败'}）"
        for c in task.get("check_results", [])
    ) or "（无）"
    inputs = "\n".join(
        f"- {i.get('player_id')}: {i.get('text')}" for i in task.get("player_inputs", [])
    ) or "（无）"
    system = (
        f"你是 NPC「{task.get('npc_name')}」。人设：{task.get('npc_persona')}。\n"
        f"当前场景：{task.get('scene_name')}。{task.get('scene_description', '')}\n"
        f"你对玩家角色的态度值：{task.get('npc_attitude', 50)}（0 敌对 - 50 中立 - 100 友善）。\n"
        f"背景记忆：{task.get('memory_context') or '（无）'}\n"
        f"最近的检定结果：\n{checks}"
    )
    user = (
        f"玩家行动：\n{inputs}\n"
        f"你被触发回应的原因：{task.get('trigger') or '玩家行动直接涉及你'}\n"
        "请以你的身份回应。"
    )
    return {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}


def _parse_reaction_text(raw: str, npc_id: str) -> dict:
    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in NPC output")
    data = json.loads(text[start:end + 1])
    return {"npc_id": npc_id, "speech": str(data.get("speech", "")),
            "action": data.get("action")}


def build_speak_node(client: LLMClient) -> Callable[[NpcTaskState], dict]:
    def speak(task: NpcTaskState) -> dict:
        messages = [ChatMessage(**m) for m in task["messages"]]
        ctx = LlmContext(task["campaign_id"], task["branch_id"], task["turn_id"])
        raw = client.chat("npc", messages, ctx)
        return {"reaction": _parse_reaction_text(raw, task["npc_id"])}

    return speak


def build_npc_subgraph(client: LLMClient):
    g = StateGraph(NpcTaskState)
    g.add_node("assemble", assemble_persona)
    g.add_node("speak", build_speak_node(client))
    g.add_edge(START, "assemble")
    g.add_edge("assemble", "speak")
    g.add_edge("speak", END)
    return g.compile()


def build_npc_worker(subgraph) -> Callable[[dict], dict]:
    def npc_respond(task: dict) -> dict:
        npc_id = task["npc_id"]
        try:
            final = subgraph.invoke(dict(task))
            reaction = final.get("reaction") or {}
        except Exception:
            reaction = {}  # 单个 NPC 失败 → 沉默占位（规格 §8），其余 NPC 不受影响
        if not reaction.get("npc_id"):
            reaction = {"npc_id": npc_id, "speech": str(reaction.get("speech", "")),
                        "action": reaction.get("action")}
        return {"npc_reactions": {npc_id: reaction}}

    return npc_respond


def build_npc_dispatch(module) -> Callable[[GameState], list[Send] | str]:
    def npc_dispatch(state: GameState) -> list[Send] | str:
        decision = state.get("decision") or {}
        triggers_raw = decision.get("proactive_npc_triggers", [])
        scene = module.scene(state["scene_id"])
        known = {n.id for n in module.npcs}

        triggers: dict[str, str] = {}
        candidates: list[str] = []
        for t in triggers_raw:
            npc_id = t.get("npc_id")
            if npc_id in known and npc_id not in candidates:
                candidates.append(npc_id)
                triggers[npc_id] = t.get("trigger", "")

        if not candidates:  # 回退：玩家行动直接点名了场景内的 NPC
            inputs_text = " ".join(i.get("text", "") for i in state.get("player_inputs", []))
            for npc_id in scene.npcs:
                if module.npc(npc_id).name in inputs_text:
                    candidates.append(npc_id)
                    break

        level = state.get("budget_level", "ok")
        if level in ("tight", "exceeded"):
            candidates = candidates[:1]  # 阶梯②：只保留首位相关 NPC
        else:
            candidates = candidates[:2]  # 正常态上限 2，防并行爆炸

        if not candidates:
            return "gm_narrate"

        tasks = []
        for npc_id in candidates:
            npc_def = module.npc(npc_id)
            tasks.append(Send("npc_respond", {
                "npc_id": npc_id,
                "trigger": triggers.get(npc_id, ""),
                "campaign_id": state["campaign_id"],
                "branch_id": state["branch_id"],
                "turn_id": state["turn_id"],
                "scene_name": scene.name,
                "scene_description": scene.description,
                "npc_name": npc_def.name,
                "npc_persona": npc_def.persona,
                "npc_attitude": state.get("npc_attitudes", {}).get(
                    npc_id, npc_def.initial_attitude),
                "memory_context": state.get("memory_context", ""),
                "player_inputs": state.get("player_inputs", []),
                "check_results": state.get("check_results", []),
            }))
        return tasks

    return npc_dispatch
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/graph -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/npc.py backend/tests/graph/test_npc.py
git commit -m "feat(graph): NPC subgraph with persona assembly and Send dispatch"
```

---

### Task 20: 记忆节点 —— memory_query（含阶梯①降档与失败回退）

**Files:**
- Create: `backend/app/graph/nodes/memory.py`
- Test: `backend/tests/graph/test_memory_node.py`

**Interfaces:**
- Consumes: `MemoryService` 协议 / `JournalMemory`（Task 13）、`GameState`（Task 14）
- Produces: `build_memory_query_node(memory) -> Callable[[GameState], dict]`
  - 正常（ok）：`get_context(campaign_id, branch_id)`（默认 1200 字符）+ 对 `decision.memory_queries[:3]` 逐个 `search(limit=2)`，命中拼接为 `【检索命中】` 块
  - 阶梯①（`budget_level in ("tight", "exceeded")`）：**降档为只给最近摘要**——`get_context(..., budget_chars=600)`，**不执行 search**
  - 任何异常 → `{"memory_context": "", "degraded": {"memory_query": True}}`（规格 §8：降级为"无长期记忆"继续，回合推进）

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_memory_node.py`：
```python
from app.graph.nodes.memory import build_memory_query_node
from app.memory.base import MemoryEvent
from app.memory.journal import JournalMemory

class SpyMemory:
    """记录调用参数、委托真实实现。"""

    def __init__(self, inner):
        self.inner = inner
        self.context_budgets: list[int] = []
        self.search_queries: list[str] = []

    def get_context(self, campaign_id, branch_id, budget_chars=1200):
        self.context_budgets.append(budget_chars)
        return self.inner.get_context(campaign_id, branch_id, budget_chars)

    def search(self, campaign_id, branch_id, query, limit=5):
        self.search_queries.append(query)
        return self.inner.search(campaign_id, branch_id, query, limit)

    def update_summaries(self, campaign_id, branch_id, turn_id):
        self.inner.update_summaries(campaign_id, branch_id, turn_id)

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "decision": {"memory_queries": ["磨坊"]},
            "budget_level": "ok", **extra}

def test_ok_path_appends_search_hits(repo, campaign):
    journal = JournalMemory(repo)
    journal.write_event(campaign.id, campaign.active_branch_id,
                        MemoryEvent(type="clue", text="磨坊夜里传出哭声", turn_id=1))
    spy = SpyMemory(journal)
    upd = build_memory_query_node(spy)(base_state(campaign))
    assert "【检索命中】" in upd["memory_context"]
    assert "磨坊夜里传出哭声" in upd["memory_context"]
    assert spy.context_budgets == [1200]
    assert spy.search_queries == ["磨坊"]

def test_tight_downgrades_to_summary_only(repo, campaign):
    journal = JournalMemory(repo)
    journal.write_event(campaign.id, campaign.active_branch_id,
                        MemoryEvent(type="clue", text="磨坊夜里传出哭声", turn_id=1))
    spy = SpyMemory(journal)
    upd = build_memory_query_node(spy)(base_state(campaign, budget_level="tight"))
    assert spy.context_budgets == [600]      # 阶梯①：budget_chars 降档
    assert spy.search_queries == []          # 不做检索
    assert "【检索命中】" not in upd["memory_context"]

def test_failure_degrades_to_empty_but_continues(repo, campaign):
    class BrokenMemory:
        def get_context(self, *a, **kw):
            raise RuntimeError("memory down")

        def search(self, *a, **kw):
            raise RuntimeError("memory down")

        def update_summaries(self, *a, **kw):
            pass

    upd = build_memory_query_node(BrokenMemory())(base_state(campaign))
    assert upd["memory_context"] == ""
    assert upd["degraded"] == {"memory_query": True}
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_memory_node.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.graph.nodes.memory'`

- [ ] **Step 3: 实现**

`backend/app/graph/nodes/memory.py`：
```python
"""记忆查询节点：为 GM/NPC 组装记忆上下文；失败降级为"无长期记忆"继续。"""
from app.graph.state import GameState

SEARCH_LIMIT_PER_QUERY = 2
MAX_QUERIES = 3


def build_memory_query_node(memory):
    def memory_query(state: GameState) -> dict:
        campaign_id, branch_id = state["campaign_id"], state["branch_id"]
        level = state.get("budget_level", "ok")
        try:
            if level in ("tight", "exceeded"):
                # 阶梯①：记忆检索降档（只给最近摘要）
                ctx = memory.get_context(campaign_id, branch_id, budget_chars=600)
            else:
                queries = (state.get("decision") or {}).get("memory_queries", [])[:MAX_QUERIES]
                hits = []
                for q in queries:
                    hits.extend(memory.search(campaign_id, branch_id, q,
                                              limit=SEARCH_LIMIT_PER_QUERY))
                ctx = memory.get_context(campaign_id, branch_id)
                if hits:
                    lines = "\n".join(f"- {h.text}" for h in hits)
                    ctx = f"{ctx}\n【检索命中】\n{lines}"
        except Exception:
            return {"memory_context": "", "degraded": {"memory_query": True}}
        return {"memory_context": ctx}

    return memory_query
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/graph -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/memory.py backend/tests/graph/test_memory_node.py
git commit -m "feat(graph): memory_query node with tier-1 downgrade and failure fallback"
```

---

### Task 21: 主图装配（GM Supervisor + NPC Send 并行 + 检查点）与集成测试

**Files:**
- Create: `backend/app/graph/main.py`
- Test: `backend/tests/graph/test_main_graph.py`

**Interfaces:**
- Consumes: 全部节点（Task 15-20）、`BudgetGuard`（Task 12）、`SqliteSaver`（langgraph-checkpoint-sqlite）
- Produces：
  - `build_checkpointer(sqlite_path: str) -> SqliteSaver`（建连接 + `setup()`；CLI 断点续玩依赖它）
  - `build_game_graph(repo, module, memory, client, guard, checkpointer=None) -> CompiledGraph`
  - 图结构（路由分支**全部**）：
    - `START → intake`；`intake` →（`error=="budget_paused"` → END **战役熔断**；否则 → `gm_decide`）
    - `gm_decide → validate`；`validate` →（error → `fallback`；否则 → `resolve_checks`）
    - `resolve_checks`（`_guarded("resolve_failed", ...)` 包装）→（error → `fallback`；否则 → `memory_query`）
    - `memory_query` →（Send 扇出 → `npc_respond`；无候选 → `gm_narrate`）
    - `npc_respond → gm_narrate`；`gm_narrate` →（error → `fallback`；否则 → `post_turn`）
    - `post_turn → wait_input`；`wait_input → intake`（resume 后开启下一回合）；`fallback → wait_input`
  - `_guarded(code, fn)`：纯代码节点真异常兜底 → `{"error": code, "degraded": {code: True}}`

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_main_graph.py`：
```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.graph.main import build_game_graph
from app.llm.client import LLMClient
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')
OPENING_NARR = "雾气贴着地面爬行。村口的老树在风里摇晃。"

def make_env(repo, mini_module, scripts_by_model, **settings_overrides):
    settings = Settings(**settings_overrides)
    pricing = Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
        "deepseek-chat": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011),
    })
    queues = {m: list(v) for m, v in scripts_by_model.items()}
    model_calls: list[str] = []

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        model_calls.append(model)
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    client = LLMClient(settings, pricing, usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, mini_module, JournalMemory(repo), client,
                             BudgetGuard(settings), MemorySaver())
    return graph, model_calls

def config_for(repo, campaign):
    branch = repo.get_branch(campaign.active_branch_id)
    return {"configurable": {"thread_id": repo.thread_id_for(branch)}}

def init_state(campaign):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 0, "player_inputs": []}

def test_opening_turn_reaches_interrupt(repo, campaign, mini_module):
    graph, calls = make_env(repo, mini_module,
                            {"qwen-plus": [OPENING_DECIDE, OPENING_NARR]})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)          # 已挂起等待输入
    assert snap.values["turn_id"] == 1           # post_turn 已推进
    assert snap.values["narration_segments"][0]["speaker"] == "gm"
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert "turn_start" in types and "narration" in types
    assert calls == ["qwen-plus", "qwen-plus"]   # decide + narrate

def test_resume_runs_full_turn_with_check(repo, campaign, mini_module, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.turn.new_seed", lambda: 42)
    turn1_decide = ('{"intent_summary": "推门", "checks": [{"actor": "pc_1", "skill": "侦查",'
                    ' "difficulty": "regular"}], "proactive_npc_triggers": [],'
                    ' "scene_transition": null, "memory_queries": []}')
    graph, calls = make_env(repo, mini_module, {"qwen-plus": [
        OPENING_DECIDE, OPENING_NARR, turn1_decide, "你推开木门，霉味扑面而来。"]})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(Command(resume={
        "turn_id": 1,
        "inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我推门进去"}],
        "skipped": [],
    }), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["turn_id"] == 2
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert len(rows) == 1 and rows[0].seed == 42 and rows[0].skill == "侦查"
    assert 1 <= snap.values["check_results"][0]["roll"] <= 100
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert types.count("check") == 1
    assert types.count("narration") == 2

def test_validate_failure_falls_back_to_wait(repo, campaign, mini_module):
    graph, calls = make_env(repo, mini_module,
                            {"qwen-plus": ["这不是 JSON", "还是不是 JSON"]})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)              # 失败不推进，回到输入等待
    assert snap.values["error"] == "decision_invalid"
    assert snap.values["narration"] == ""
    assert snap.values["turn_id"] == 0
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert "narration" not in types and "check" not in types

def test_paused_halts_without_llm(repo, campaign, mini_module):
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen-plus",
                      1, 1, 5.0, 100)  # 成本超过默认上限 2.0
    graph, calls = make_env(repo, mini_module, {})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ()                           # 图结束（战役熔断，无挂起）
    assert snap.values["error"] == "budget_paused"
    assert calls == []                               # 没有任何 LLM 调用
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_main_graph.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.graph.main'`

- [ ] **Step 3: 实现**

`backend/app/graph/main.py`：
```python
"""主图装配：GM Supervisor + NPC 子图 Send 并行 + 检查点（M2 单机闭环核心）。

路由语义（与规格 §4/§8 一致）：
- 失败不推进 → fallback → wait_input（本轮 pending 丢弃，玩家重来）
- 战役熔断（④）→ 直接结束图，等待手动调高预算
"""
import sqlite3
from typing import Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.graph.npc import build_npc_dispatch, build_npc_subgraph, build_npc_worker
from app.graph.nodes.gm import build_decide_node, build_narrate_node, build_validate_node
from app.graph.nodes.memory import build_memory_query_node
from app.graph.nodes.turn import (build_intake_node, build_post_turn_node,
                                  build_resolve_checks_node, fallback, wait_input)
from app.graph.state import GameState


def build_checkpointer(sqlite_path: str) -> SqliteSaver:
    """SqliteSaver：CLI 重启后仍可恢复挂起的回合（断点续玩）。"""
    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _guarded(code: str, fn: Callable) -> Callable:
    """纯代码节点真异常兜底 → 标记错误，交由统一 fallback（规格 §8）。"""

    def wrapped(state: GameState) -> dict:
        try:
            return fn(state)
        except Exception:
            return {"error": code, "degraded": {code: True}}

    return wrapped


def _route_after_intake(state: GameState) -> str:
    return "halt" if state.get("error") == "budget_paused" else "gm_decide"


def _route_after_validate(state: GameState) -> str:
    return "fallback" if state.get("error") else "resolve_checks"


def _route_after_resolve(state: GameState) -> str:
    return "fallback" if state.get("error") else "memory_query"


def _route_after_narrate(state: GameState) -> str:
    return "fallback" if state.get("error") else "post_turn"


def build_game_graph(repo, module, memory, client, guard, checkpointer=None):
    g = StateGraph(GameState)
    g.add_node("intake", build_intake_node(repo, module, guard))
    g.add_node("gm_decide", build_decide_node(client, module))
    g.add_node("validate", build_validate_node(client))
    g.add_node("resolve_checks",
               _guarded("resolve_failed", build_resolve_checks_node(repo)))
    g.add_node("memory_query", build_memory_query_node(memory))
    g.add_node("npc_respond", build_npc_worker(build_npc_subgraph(client)))
    g.add_node("gm_narrate", build_narrate_node(client, module))
    g.add_node("post_turn", build_post_turn_node(repo, memory))
    g.add_node("wait_input", wait_input)
    g.add_node("fallback", fallback)

    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", _route_after_intake,
                            {"halt": END, "gm_decide": "gm_decide"})
    g.add_edge("gm_decide", "validate")
    g.add_conditional_edges("validate", _route_after_validate,
                            {"fallback": "fallback", "resolve_checks": "resolve_checks"})
    g.add_conditional_edges("resolve_checks", _route_after_resolve,
                            {"fallback": "fallback", "memory_query": "memory_query"})
    g.add_conditional_edges("memory_query", build_npc_dispatch(module),
                            ["npc_respond", "gm_narrate"])
    g.add_edge("npc_respond", "gm_narrate")   # Send 各分支全部完成后汇合
    g.add_conditional_edges("gm_narrate", _route_after_narrate,
                            {"fallback": "fallback", "post_turn": "post_turn"})
    g.add_edge("post_turn", "wait_input")
    g.add_edge("wait_input", "intake")        # interrupt 恢复后开启下一回合
    g.add_edge("fallback", "wait_input")      # 失败不推进：重新收集输入
    return g.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/graph -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/main.py backend/tests/graph/test_main_graph.py
git commit -m "feat(graph): main graph assembly with checkpointing and full-turn integration"
```

---

### Task 22: 预算熔断阶梯与降级路径（图级集成测试）

**Files:**
- Create: `backend/tests/graph/test_degradation_paths.py`

**Interfaces:**
- Consumes: `build_game_graph`（Task 21）、`SpyMemory` 模式、全套节点
- Produces: 覆盖规格 §8 降级矩阵与 §9 熔断阶梯 ①②③ 的图级用例（④ 由 Task 21 的 `test_paused_halts_without_llm` 覆盖、validate repair 失败由 `test_validate_failure_falls_back_to_wait` 覆盖、NPC 沉默单元级由 Task 19 覆盖，此处补图级）

- [ ] **Step 1: 写测试（复用 Task 21 的 make_env 结构，增加 memory 参数）**

`backend/tests/graph/test_degradation_paths.py`：
```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.graph.main import build_game_graph
from app.llm.client import LLMClient
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')
OPENING_NARR = "雾气贴着地面爬行。村口的老树在风里摇晃。"
PLAIN_DECIDE = ('{"intent_summary": "继续", "checks": [], "proactive_npc_triggers": [],'
                ' "scene_transition": null, "memory_queries": []}')
RESUME_TURN1 = Command(resume={"turn_id": 1, "inputs": [
    {"player_id": "p1", "character_id": "pc_1", "text": "我推门进去"}], "skipped": []})

class SpyMemory:
    def __init__(self, inner):
        self.inner = inner
        self.context_budgets: list[int] = []
        self.search_queries: list[str] = []

    def get_context(self, campaign_id, branch_id, budget_chars=1200):
        self.context_budgets.append(budget_chars)
        return self.inner.get_context(campaign_id, branch_id, budget_chars)

    def search(self, campaign_id, branch_id, query, limit=5):
        self.search_queries.append(query)
        return self.inner.search(campaign_id, branch_id, query, limit)

    def update_summaries(self, campaign_id, branch_id, turn_id):
        self.inner.update_summaries(campaign_id, branch_id, turn_id)

def make_env(repo, mini_module, scripts_by_model, memory=None, **settings_overrides):
    settings = Settings(**settings_overrides)
    pricing = Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
        "deepseek-chat": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011),
    })
    queues = {m: list(v) for m, v in scripts_by_model.items()}
    model_calls: list[str] = []

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        model_calls.append(model)
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    client = LLMClient(settings, pricing, usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, mini_module, memory or JournalMemory(repo), client,
                             BudgetGuard(settings), MemorySaver())
    return graph, model_calls

def config_for(repo, campaign):
    branch = repo.get_branch(campaign.active_branch_id)
    return {"configurable": {"thread_id": repo.thread_id_for(branch)}}

def init_state(campaign):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 0, "player_inputs": []}

def test_tight_downgrades_memory_and_shrinks_npc(repo, campaign, mini_module):
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen-plus",
                      10, 20, 0.8, 100)  # cap=1.0 → 0.8 ∈ [0.7, 1.0) → TIGHT
    tight_decide = ('{"intent_summary": "接近", "checks": [], "proactive_npc_triggers":'
                    ' [{"npc_id": "guard", "trigger": "玩家靠近"}, {"npc_id": "barkeep"}],'
                    ' "scene_transition": null, "memory_queries": ["磨坊"]}')
    spy = SpyMemory(JournalMemory(repo))
    graph, calls = make_env(repo, mini_module, {
        "qwen-plus": [OPENING_DECIDE, OPENING_NARR, tight_decide, "守卫的目光钉在你身上。"],
        "deepseek-chat": ['{"speech": "站住。", "action": "伸手拦路"}'],
    }, memory=spy, campaign_cost_cap_usd=1.0)
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert spy.context_budgets == [600, 600]      # 阶梯①：记忆降档（开场 + 第 1 回合）
    assert spy.search_queries == []               # 降档后不做检索
    assert calls.count("deepseek-chat") == 1      # 阶梯②：两个 trigger 收缩到首位
    assert "qwen-turbo" not in calls              # TIGHT 尚未到 ③

def test_exceeded_switches_gm_to_cheap_model(repo, campaign, mini_module):
    repo.record_usage(campaign.id, campaign.active_branch_id, 1, "gm", "qwen-plus",
                      20000, 15000, 0.1, 100)  # 第 1 回合 35000 tokens ≥ 30000 → EXCEEDED
    spy = SpyMemory(JournalMemory(repo))
    graph, calls = make_env(repo, mini_module, {
        "qwen-plus": [OPENING_DECIDE, OPENING_NARR],
        "qwen-turbo": [PLAIN_DECIDE, "风穿过空荡的街道。"],
    }, memory=spy)
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    calls.clear()  # 只看第 1 回合的模型选择
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",) and snap.values["turn_id"] == 2
    assert "qwen-plus" not in calls               # 阶梯③：GM（decide+narrate）全换便宜档
    assert calls.count("qwen-turbo") == 2
    assert spy.context_budgets == [600]           # 阶梯①同样生效（逐级累积）

def test_resolve_failure_falls_back(repo, campaign, mini_module, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("dice broken")

    monkeypatch.setattr("app.graph.nodes.turn.roll_check", boom)
    check_decide = ('{"intent_summary": "观察", "checks": [{"actor": "pc_1", "skill": "侦查"}],'
                    ' "proactive_npc_triggers": [], "scene_transition": null,'
                    ' "memory_queries": []}')
    graph, calls = make_env(repo, mini_module,
                            {"qwen-plus": [OPENING_DECIDE, OPENING_NARR, check_decide]})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["error"] == "resolve_failed"   # 纯代码节点兜底（_guarded）
    assert snap.values["degraded"]["resolve_failed"] is True
    assert snap.values["turn_id"] == 1                # 失败不推进

class BrokenGetContextMemory:
    """get_context/search 故障但 update_summaries 正常：只应降级记忆查询。"""

    def get_context(self, *args, **kwargs):
        raise RuntimeError("memory down")

    def search(self, *args, **kwargs):
        raise RuntimeError("memory down")

    def update_summaries(self, campaign_id, branch_id, turn_id):
        pass

def test_memory_failure_continues_turn(repo, campaign, mini_module):
    graph, calls = make_env(repo, mini_module, {
        "qwen-plus": [OPENING_DECIDE, OPENING_NARR, PLAIN_DECIDE, "你环顾四周，一切如常。"],
    }, memory=BrokenGetContextMemory())
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["turn_id"] == 2                # 回合推进（记忆是增强非阻塞）
    assert snap.values["degraded"]["memory_query"] is True
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert "narration" in types

def test_silent_npc_still_narrates(repo, campaign, mini_module):
    trigger_decide = ('{"intent_summary": "与守卫交涉", "checks": [],'
                      ' "proactive_npc_triggers": [{"npc_id": "guard",'
                      ' "trigger": "玩家试图进城"}], "scene_transition": null,'
                      ' "memory_queries": []}')
    graph, calls = make_env(repo, mini_module, {
        "qwen-plus": [OPENING_DECIDE, OPENING_NARR, trigger_decide, "守卫只是沉默地看着你。"],
        "deepseek-chat": [],   # 脚本耗尽 → NPC 调用抛异常 → 静默占位
    })
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["turn_id"] == 2
    assert snap.values["npc_reactions"]["guard"]["speech"] == ""  # 沉默占位
    assert snap.values["error"] is None                           # 其余流程正常
```

- [ ] **Step 2: 运行测试**

Run: `cd backend; uv run pytest tests/graph/test_degradation_paths.py -q`
Expected: PASS（6 passed）

- [ ] **Step 3: 全量回归**

Run: `cd backend; uv run pytest -q`
Expected: PASS（全部通过）

- [ ] **Step 4: Commit**

```bash
git add backend/tests/graph/test_degradation_paths.py
git commit -m "test(graph): budget ladder and degradation path coverage"
```

---

### Task 23: 回放脚手架（--record / 离线回放）+ 示例模组 misty_hollow

**Files:**
- Create: `backend/tests/harness/__init__.py`（空）、`backend/tests/harness/replay.py`
- Modify: `backend/tests/conftest.py`（顶部加 sys.path 保障；尾部加 `--record` 选项与 `record_mode` fixture）
- Create: `modules/misty_hollow.yaml`（原创示例模组：兼回放基线、演示与 Task 24 的 CLI 内容）
- Create: `backend/tests/fixtures/misty_hollow/smoke/turn_0.json`、`backend/tests/fixtures/misty_hollow/smoke/turn_1.json`
- Create: `backend/tests/graph/test_replay_smoke.py`

**Interfaces:**
- Consumes: `LLMClient`/`OpenAICompatModel`（Task 11）、`build_game_graph`（Task 21）、`load_module`（Task 6）
- Produces：
  - `ReplayModels(entries: list[dict])`：`factory(model, base_url, api_key)`（符合 `ModelFactory` 签名）+ `chat(messages)`；**录制顺序错位立即断言失败**；`calls` 记录全部请求
  - `load_turn(path) -> dict` / `save_turn(path, payload) -> None`
  - `build_replay_client(settings, pricing, fixture_paths: str|Path|list, usage_sink=None) -> tuple[LLMClient, ReplayModels]`（多文件响应串联）
  - `make_recording_factory(inner_factory, collected) -> ModelFactory`；`build_recording_client(settings, pricing, usage_sink=None, real_factory=None) -> tuple[LLMClient, list[dict]]`
  - fixture 格式（规格 §11）：`{"responses": [{"model", "text"}, ...], "seeds": [int, ...]}`
  - `--record`：用真实 LLM 重录基线（需 key + 网络）；**默认模式零网络零 key**

- [ ] **Step 1: 创建 harness 包与回放模块**

`backend/tests/harness/__init__.py`：留空。

`backend/tests/harness/replay.py`：
```python
"""录制回放：默认零网络零 key；--record 时用真实模型重录基线。

fixture 格式（tests/fixtures/{module}/{scenario}/turn_{n}.json）：
{"responses": [{"model": "qwen-plus", "text": "..."}, ...],  # 按请求时间顺序
 "seeds": [123, ...]}                                         # 本回合骰子 seed（可选）
"""
import json
from pathlib import Path

from app.llm.client import ChatResponse, LLMClient, OpenAICompatModel


class ReplayModels:
    """ChatModel 工厂 + 回放器：按录制顺序返回响应，顺序错位即断言失败。"""

    def __init__(self, entries: list[dict]):
        self.entries = list(entries)
        self.index = 0
        self.calls: list[dict] = []
        self._current_model = ""

    def factory(self, model: str, base_url: str | None, api_key: str | None):
        self._current_model = model
        return self

    def chat(self, messages):
        if self.index >= len(self.entries):
            raise IndexError("replay entries exhausted")
        entry = self.entries[self.index]
        self.index += 1
        assert entry["model"] == self._current_model, (
            f"回放顺序错位：录制为 {entry['model']}，本次请求路由到 {self._current_model}")
        self.calls.append({"model": self._current_model,
                           "messages": [m.model_dump() for m in messages]})
        return ChatResponse(text=entry["text"], tokens_in=10, tokens_out=20)


def load_turn(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_turn(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_replay_client(settings, pricing, fixture_paths, usage_sink=None):
    paths = fixture_paths if isinstance(fixture_paths, list) else [fixture_paths]
    entries: list[dict] = []
    for p in paths:
        entries.extend(load_turn(p)["responses"])
    replay = ReplayModels(entries)
    client = LLMClient(settings, pricing, usage_sink=usage_sink,
                       model_factory=replay.factory)
    return client, replay


def make_recording_factory(inner_factory, collected: list[dict]):
    """把真实模型的每次响应记入 collected（供 --record 落盘）。"""

    def factory(model: str, base_url: str | None, api_key: str | None):
        inner = inner_factory(model, base_url, api_key)

        class _RecordingModel:
            def chat(self, messages):
                resp = inner.chat(messages)
                collected.append({"model": model, "text": resp.text})
                return resp

        return _RecordingModel()

    return factory


def build_recording_client(settings, pricing, usage_sink=None, real_factory=None):
    """--record 模式：真实调用 + 录制响应。"""
    collected: list[dict] = []
    inner_factory = real_factory or (
        lambda model, base_url, api_key: OpenAICompatModel(
            api_key=api_key, base_url=base_url, model=model,
            timeout_seconds=settings.request_timeout_seconds))
    client = LLMClient(settings, pricing, usage_sink=usage_sink,
                       model_factory=make_recording_factory(inner_factory, collected))
    return client, collected
```

- [ ] **Step 2: 修改 conftest.py（两处）**

**顶部**改为：
```python
import sys
from pathlib import Path

# 确保 `import harness.replay` 稳定可用（不依赖 pytest 的 prepend 行为）
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from app.content.schema import Module
```

**文件末尾追加**：
```python
def pytest_addoption(parser):
    parser.addoption("--record", action="store_true", default=False,
                     help="使用真实 LLM 重录回放基线（需要 API key 与网络）")


@pytest.fixture
def record_mode(pytestconfig) -> bool:
    return bool(pytestconfig.getoption("--record"))
```

- [ ] **Step 3: 创建示例模组**

`modules/misty_hollow.yaml`：
```yaml
meta:
  id: misty_hollow
  title: 雾霭镇的低语
  author: Ensemble
  version: "0.1"
  system: coc-lite

opening:
  narration: |
    1927 年深秋，你们乘坐的班车在雾霭镇外的岔路口抛了锚。
    司机怎么也不肯再往前开：「前面那座镇子……最近不太干净。」
    暮色四合，雾从山谷里漫上来，把镇口的石桥吞掉了一半。
  scene_id: square
  player_goal: 查明磨坊学徒失踪的真相，并决定如何对待镇上的「低语」。

scenes:
  - id: square
    name: 镇中心广场
    description: 石砌广场中央立着一座被磨平了五官的旧神像，四周店铺多半关了门。
    npcs: [elder]
    exits: [inn, mill]
    clues: [clue_missing]
  - id: inn
    name: 白鹭旅店
    description: 镇上唯一还亮着灯的旅店，壁炉的火烧得很旺，客人们却压低声音说话。
    npcs: [innkeeper]
    exits: [square]
    clues: [clue_diary]
  - id: mill
    name: 老磨坊
    description: 河边的磨坊早已停转，木门上贴着褪色的封条，麦壳从门缝里漏出来。
    npcs: [miller]
    exits: [square, cellar]
    clues: [clue_wheat]
  - id: cellar
    name: 磨坊地窖
    description: 潮湿的石阶通向地底，墙壁上刻满了无人能辨的纹路，空气里有股铁锈味。
    npcs: [whisperer]
    exits: [mill]
    clues: [clue_altar]

npcs:
  - id: elder
    name: 陈长老
    persona: 镇上年岁最长的老人，说话极慢，每句话都像掂量过重量；他知道神像与低语的事，但只在信任建立后吐露。
    knowledge: [神像的来历, 十年前的那场「献祭」]
    initial_attitude: 40
  - id: innkeeper
    name: 何老板
    persona: 健谈而热络的旅店老板，消息灵通，但谈及磨坊时总会突然岔开话题。
    knowledge: [镇上近况, 客人失踪的传闻]
    initial_attitude: 60
  - id: miller
    name: 磨坊主老赵
    persona: 自从学徒失踪后整日酗酒的消瘦男人，悔恨与恐惧交织，提防任何打听地窖的人。
    knowledge: [学徒失踪当晚的细节, 地窖的门锁在哪]
    initial_attitude: 30
  - id: whisperer
    name: 低语者
    persona: 栖身地窖的存在，用多重叠音说话，自称是「守约者」，试图与来者做一笔关于记忆的交易。
    knowledge: [镇子的旧约, 神像的秘密]
    initial_attitude: 50

clues:
  - id: clue_missing
    content: 公告栏上贴着泛黄的寻人启事：学徒小满，三个月前失踪，最后目击地在老磨坊。
    unlocks: ["clue:clue_diary"]
  - id: clue_diary
    content: 旅店客人遗落的日记提到：「满月夜里，地窖的门自己开了。」
    unlocks: ["clue:clue_wheat"]
  - id: clue_wheat
    content: 磨坊的麦堆里混着黑色的穗子，捻碎后散发出与神像同样的石粉味。
    unlocks: ["clue:clue_altar"]
  - id: clue_altar
    content: 地窖深处有一圈刻满纹路的石台，中央的凹槽尺寸恰好放得下一个人。
    unlocks: []

endings:
  - id: ending_break
    scene: cellar
    condition: 摧毁石台、终结旧约（需要掌握「地窖祭坛」的真相）
  - id: ending_flee
    scene: square
    condition: 在天亮前带着幸存者离开雾霭镇
```

- [ ] **Step 4: 创建回放基线 fixtures（手工编写的确定性基线；--record 可重录）**

`backend/tests/fixtures/misty_hollow/smoke/turn_0.json`（开场：decide → NPC → narrate）：
```json
{
  "responses": [
    {"model": "qwen-plus", "text": "{\"intent_summary\": \"开场：玩家抵达镇口\", \"checks\": [], \"proactive_npc_triggers\": [{\"npc_id\": \"elder\", \"trigger\": \"长老在广场等着来客\"}], \"scene_transition\": null, \"memory_queries\": []}"},
    {"model": "deepseek-chat", "text": "{\"speech\": \"你们就是信里说的外乡人？近来镇上……不太平。\", \"action\": \"拄着拐杖从神像旁踱出来\"}"},
    {"model": "qwen-plus", "text": "暮色把雾霭镇压得很低。广场中央的神像没有脸，只有一片被磨平的石面。[[npc:elder]]你们就是信里说的外乡人？近来镇上……不太平。[[/npc]]老人的目光在你们脸上停了很久。"}
  ],
  "seeds": []
}
```

`backend/tests/fixtures/misty_hollow/smoke/turn_1.json`（第 1 回合：decide 含 1 检定 → NPC → narrate；seed 固定可复现）：
```json
{
  "responses": [
    {"model": "qwen-plus", "text": "{\"intent_summary\": \"向陈长老打听失踪的学徒\", \"checks\": [{\"actor\": \"pc_p1\", \"skill\": \"话术\", \"difficulty\": \"regular\"}], \"proactive_npc_triggers\": [{\"npc_id\": \"elder\", \"trigger\": \"玩家当面问起失踪案\"}], \"scene_transition\": null, \"memory_queries\": [\"学徒失踪\"]}"},
    {"model": "deepseek-chat", "text": "{\"speech\": \"三个月了……老赵的学徒进了地窖，再没出来。你们要查，就去旅店找何老板拿日记。\", \"action\": \"压低声音，目光扫向磨坊方向\"}"},
    {"model": "qwen-plus", "text": "长老的声音在雾气里发颤。[[npc:elder]]三个月了……老赵的学徒进了地窖，再没出来。[[/npc]]他顿了顿，抬手指向街角还亮着灯的白鹭旅店。"}
  ],
  "seeds": [20260924]
}
```

- [ ] **Step 5: 写回放测试**

`backend/tests/graph/test_replay_smoke.py`：
```python
"""整局脚本回放：确定性跑通开场 + 第一回合（零网络零 key）。"""
import os
from dataclasses import asdict
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import load_pricing, load_settings
from app.content.loader import load_module
from app.graph.main import build_game_graph
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.rules.character import make_default_character
from harness.replay import build_recording_client, build_replay_client, load_turn, save_turn

TESTS_DIR = Path(__file__).resolve().parents[1]          # backend/tests
ROOT = Path(__file__).resolve().parents[3]               # 仓库根
FIXTURE_DIR = TESTS_DIR / "fixtures" / "misty_hollow" / "smoke"
MODULES_DIR = ROOT / "modules"

def test_misty_hollow_module_is_valid():
    module = load_module(MODULES_DIR / "misty_hollow.yaml")  # 校验不过即抛
    assert len(module.scenes) >= 4 and len(module.npcs) >= 4
    assert module.opening.scene_id == "square"

def _setup(monkeypatch, repo, client):
    settings = load_settings()
    module = load_module(MODULES_DIR / "misty_hollow.yaml")
    campaign = repo.create_campaign(module.meta.id, "回放冒烟")
    char = make_default_character("p1", "调查员")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    graph = build_game_graph(repo, module, JournalMemory(repo), client,
                             BudgetGuard(settings), MemorySaver())
    branch = repo.get_branch(campaign.active_branch_id)
    cfg = {"configurable": {"thread_id": repo.thread_id_for(branch)}}
    return settings, module, campaign, graph, cfg

def test_smoke_replay_offline(repo, monkeypatch):
    settings = load_settings()
    pricing = load_pricing(ROOT / "config" / "pricing.yaml")

    seeds = list(load_turn(FIXTURE_DIR / "turn_1.json").get("seeds", []))
    monkeypatch.setattr("app.graph.nodes.turn.new_seed", lambda: seeds.pop(0))

    client, replay = build_replay_client(
        settings, pricing, [FIXTURE_DIR / "turn_0.json", FIXTURE_DIR / "turn_1.json"],
        usage_sink=repo)
    _, module, campaign, graph, cfg = _setup(monkeypatch, repo, client)

    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",) and snap.values["turn_id"] == 1

    graph.invoke(Command(resume={"turn_id": 1, "inputs": [
        {"player_id": "p1", "character_id": "pc_p1", "text": "我向陈长老打听失踪的学徒"}],
        "skipped": []}), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["turn_id"] == 2 and snap.values["error"] is None

    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert len(rows) == 1 and rows[0].seed == 20260924 and rows[0].skill == "话术"

    assert [s["speaker"] for s in snap.values["narration_segments"]] == \
        ["gm", "npc:elder", "gm"]
    assert snap.values["npc_reactions"]["elder"]["speech"].startswith("三个月了")

    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert types.count("narration") == 2 and types.count("check") == 1
    assert replay.index == 6          # 全部录制响应按序精确消耗
    assert replay.calls[1]["model"] == "deepseek-chat"

def test_record_mode_writes_new_baseline(repo, monkeypatch, record_mode):
    """--record：真实调用并把新基线写回 fixtures（需 DASHSCOPE/DEEPSEEK key）。"""
    if not record_mode:
        pytest.skip("未启用 --record（默认回放零网络）")
    if not (os.environ.get("DASHSCOPE_API_KEY") and os.environ.get("DEEPSEEK_API_KEY")):
        pytest.skip("缺少 API key，无法录制")

    settings = load_settings()
    pricing = load_pricing(ROOT / "config" / "pricing.yaml")
    client, collected = build_recording_client(settings, pricing, usage_sink=repo)
    _, module, campaign, graph, cfg = _setup(monkeypatch, repo, client)

    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    save_turn(FIXTURE_DIR / "turn_0.json", {"responses": collected, "seeds": []})
    assert collected, "未录制到任何响应"
```

- [ ] **Step 6: 运行测试**

Run: `cd backend; uv run pytest tests/graph/test_replay_smoke.py -q`
Expected: PASS（`2 passed, 1 skipped`——skipped 为 --record 专用用例；若模组校验失败，先修 YAML）

- [ ] **Step 7: 全量回归**

Run: `cd backend; uv run pytest -q`
Expected: PASS（全部通过）

- [ ] **Step 8: Commit**

```bash
git add backend/tests/harness backend/tests/conftest.py modules/misty_hollow.yaml backend/tests/fixtures backend/tests/graph/test_replay_smoke.py
git commit -m "feat(test): record/replay harness with misty hollow baseline fixtures"
```

---

### Task 24: 单机 CLI（new / play / 断点续玩）+ 手动验收

**Files:**
- Create: `backend/app/cli.py`
- Modify: `backend/pyproject.toml`（追加 `[project.scripts]`）
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `assemble` 链路（Task 1-23 全部）、`build_checkpointer`/`build_game_graph`（Task 21）
- Produces：
  - `AppContext`（dataclass：`settings, repo, module, client, guard, memory, graph`）
  - `assemble(settings, module_path) -> AppContext`（同一 sqlite 文件承载 L2 + 检查点；`repo` 直接作为 usage_sink，签名已对齐）
  - `render_narration(segments, module) -> list[str]`（`gm` → 原文；`npc:<id>` → `【NPC 名】台词`）
  - `play_loop(graph, config, module, turn_id, input_fn, print_fn) -> str`（`"quit"` / `"paused"`；退出语：`quit/exit/q/退出`）
  - `run_play(ctx, campaign_id, input_fn=input, print_fn=print) -> str`：全新线程 → 跑开场；`next == ("wait_input",)` → **断点续玩**（打印"读取存档，继续运行"）；已结束 → 直接返回
  - `main(argv=None) -> int`：`new <module_path> <title>`（建战役 + 默认角色）、`play <campaign_id> <module_path>`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_cli.py`：
```python
from dataclasses import asdict

from langgraph.checkpoint.memory import MemorySaver

from app.cli import AppContext, play_loop, render_narration, run_play
from app.config import Pricing, PricingEntry, Settings
from app.graph.main import build_checkpointer, build_game_graph
from app.llm.client import LLMClient
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.rules.character import make_default_character

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')
OPENING_NARR = "雾气贴着地面爬行。村口的老树在风里摇晃。"
PLAIN_DECIDE = ('{"intent_summary": "继续", "checks": [], "proactive_npc_triggers": [],'
                ' "scene_transition": null, "memory_queries": []}')

def make_pricing():
    return Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
        "deepseek-chat": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011)})

def make_env(repo, mini_module, scripts_by_model, checkpointer=None, settings=None):
    settings = settings or Settings()
    queues = {m: list(v) for m, v in scripts_by_model.items()}
    model_calls: list[str] = []

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        model_calls.append(model)
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    client = LLMClient(settings, make_pricing(), usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, mini_module, JournalMemory(repo), client,
                             BudgetGuard(settings), checkpointer or MemorySaver())
    return graph, model_calls

def config_for(repo, campaign):
    branch = repo.get_branch(campaign.active_branch_id)
    return {"configurable": {"thread_id": repo.thread_id_for(branch)}}

def test_render_narration_marks_speakers(mini_module):
    segments = [{"speaker": "gm", "text": "风起了。"},
                {"speaker": "npc:guard", "text": "站住！"}]
    assert render_narration(segments, mini_module) == ["风起了。", "【王守卫】站住！"]

def test_play_loop_runs_turn_then_quits(repo, campaign, mini_module):
    graph, calls = make_env(repo, mini_module, {"qwen-plus": [
        OPENING_DECIDE, OPENING_NARR, PLAIN_DECIDE, "你推门进去，灯影摇晃。"]})
    cfg = config_for(repo, campaign)
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    turn_id = graph.get_state(cfg).tasks[0].interrupts[0].value["turn_id"]

    inputs = iter(["我推门进去", "退出"])
    lines: list[str] = []
    code = play_loop(graph, cfg, mini_module, turn_id, lambda _: next(inputs), lines.append)
    assert code == "quit"
    assert any("灯影摇晃" in line for line in lines)      # 第二回合叙事已渲染
    assert graph.get_state(cfg).values["turn_id"] == 2

def test_run_play_reports_paused(repo, campaign, mini_module):
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen-plus",
                      1, 1, 5.0, 100)                     # 超过默认成本上限 2.0
    graph, calls = make_env(repo, mini_module, {})        # 不应发生任何 LLM 调用
    lines: list[str] = []
    ctx = AppContext(settings=Settings(), repo=repo, module=mini_module, client=None,
                     guard=None, memory=None, graph=graph)
    code = run_play(ctx, campaign.id, input_fn=lambda _: "x", print_fn=lines.append)
    assert code == "paused"
    assert any("预算" in line for line in lines)
    assert calls == []

def test_resume_after_process_restart(tmp_path, mini_module):
    """M2 出口标准：模拟进程重启（新连接 + 新图），断点续玩成立。"""
    from app.storage.db import init_db, make_engine
    from app.storage.repo import SqliteRepository

    db = str(tmp_path / "ensemble.db")
    settings = Settings(sqlite_path=db)
    scripts = {"qwen-plus": [OPENING_DECIDE, OPENING_NARR, PLAIN_DECIDE,
                             "灯影摇晃，走廊尽头传来脚步声。"]}
    queues = {m: list(v) for m, v in scripts.items()}

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    # ---- 第一次“进程”：建局 + 跑开场，随后模拟退出 ----
    engine1 = make_engine(db)
    init_db(engine1)
    repo1 = SqliteRepository(engine1)
    campaign = repo1.create_campaign(mini_module.meta.id, "续玩测试")
    char = make_default_character("p1", "调查员")
    repo1.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    client1 = LLMClient(settings, make_pricing(), usage_sink=repo1, model_factory=factory)
    graph1 = build_game_graph(repo1, mini_module, JournalMemory(repo1), client1,
                              BudgetGuard(settings), build_checkpointer(db))
    cfg = {"configurable": {
        "thread_id": repo1.thread_id_for(repo1.get_branch(campaign.active_branch_id))}}
    graph1.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                   "turn_id": 0, "player_inputs": []}, cfg)
    assert graph1.get_state(cfg).next == ("wait_input",)

    # ---- 第二次“进程”：全新连接与图，续玩 ----
    engine2 = make_engine(db)
    init_db(engine2)
    repo2 = SqliteRepository(engine2)
    client2 = LLMClient(settings, make_pricing(), usage_sink=repo2, model_factory=factory)
    graph2 = build_game_graph(repo2, mini_module, JournalMemory(repo2), client2,
                              BudgetGuard(settings), build_checkpointer(db))
    snap = graph2.get_state(cfg)
    assert snap.next == ("wait_input",)                   # 挂起状态被恢复
    ctx2 = AppContext(settings=settings, repo=repo2, module=mini_module, client=client2,
                      guard=BudgetGuard(settings), memory=JournalMemory(repo2), graph=graph2)
    inputs = iter(["我推门进去", "退出"])
    lines: list[str] = []
    code = run_play(ctx2, campaign.id, input_fn=lambda _: next(inputs), print_fn=lines.append)
    assert code == "quit"
    assert any("读取存档" in line for line in lines)       # 走了断点续玩分支
    assert graph2.get_state(cfg).values["turn_id"] == 2   # 新进程成功推进了一个回合
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/test_cli.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.cli'`

- [ ] **Step 3: 实现**

`backend/app/cli.py`：
```python
"""单机 CLI：新建战役 / 开跑 / 断点续玩（M2 出口验收）。"""
import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from langgraph.types import Command

from app.config import Settings, load_pricing, load_settings
from app.content.loader import load_module
from app.graph.main import build_checkpointer, build_game_graph
from app.llm.client import LLMClient
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

PLAYER_ID = "p1"
QUIT_WORDS = {"quit", "exit", "q", "退出"}


@dataclass
class AppContext:
    settings: Settings
    repo: SqliteRepository
    module: object
    client: LLMClient | None
    guard: BudgetGuard | None
    memory: JournalMemory | None
    graph: object


def assemble(settings: Settings, module_path: str | Path) -> AppContext:
    """装配全部组件；L2 与检查点共用同一 SQLite 文件（CLI 单进程顺序访问）。"""
    repo = SqliteRepository(make_engine(settings.sqlite_path))
    init_db(repo.engine)
    module = load_module(module_path)
    pricing = load_pricing(settings.pricing_path)
    client = LLMClient(settings, pricing, usage_sink=repo)
    guard = BudgetGuard(settings)
    memory = JournalMemory(repo)
    graph = build_game_graph(repo, module, memory, client, guard,
                             build_checkpointer(settings.sqlite_path))
    return AppContext(settings=settings, repo=repo, module=module, client=client,
                      guard=guard, memory=memory, graph=graph)


def render_narration(segments: list[dict], module) -> list[str]:
    lines = []
    for s in segments:
        if s["speaker"] == "gm":
            lines.append(s["text"])
        else:
            npc_id = s["speaker"].split(":", 1)[1]
            try:
                name = module.npc(npc_id).name
            except KeyError:
                name = npc_id
            lines.append(f"【{name}】{s['text']}")
    return lines


def play_loop(graph, config, module, turn_id: int, input_fn, print_fn) -> str:
    """输入 → 恢复图 → 渲染，循环直到退出或熔断。返回 "quit" 或 "paused"。"""
    while True:
        try:
            text = input_fn(">> ")
        except (EOFError, KeyboardInterrupt):
            print_fn("（已退出，存档保留；再次运行 play 可继续）")
            return "quit"
        if text is None or text.strip().lower() in QUIT_WORDS:
            print_fn("（已退出，存档保留；再次运行 play 可继续）")
            return "quit"

        result = graph.invoke(Command(resume={
            "turn_id": turn_id,
            "inputs": [{"player_id": PLAYER_ID, "character_id": f"pc_{PLAYER_ID}",
                        "text": text.strip()}],
            "skipped": [],
        }), config)
        interrupts = result.get("__interrupt__")
        if interrupts:
            turn_id = interrupts[0].value["turn_id"]

        if result.get("error") == "budget_paused":
            print_fn("本局预算已熔断暂停（budget paused）。调高上限后重新运行 play。")
            return "paused"
        if result.get("error"):
            print_fn(f"（本回合失败：{result['error']}，请重新输入）")
            continue

        for line in render_narration(result.get("narration_segments", []), module):
            print_fn(line)
        if not interrupts:
            print_fn("（图执行结束）")
            return "quit"


def run_play(ctx: AppContext, campaign_id: str, input_fn=input, print_fn=print) -> str:
    campaign = ctx.repo.get_campaign(campaign_id)
    branch = ctx.repo.get_branch(campaign.active_branch_id)
    config = {"configurable": {"thread_id": ctx.repo.thread_id_for(branch)}}
    snap = ctx.graph.get_state(config)

    if snap.next == ("wait_input",):
        # 断点续玩：图挂在 wait_input（进程重启后同样成立）
        print_fn("（读取存档，继续运行）")
        tasks = snap.tasks or ()
        interrupts = tasks[0].interrupts if tasks else ()
        turn_id = (interrupts[0].value["turn_id"] if interrupts
                   else int(snap.values.get("turn_id", 0)))
        return play_loop(ctx.graph, config, ctx.module, turn_id, input_fn, print_fn)

    if snap.next:
        print_fn(f"（图处于中间状态 {snap.next}，无法续玩，请重新启动）")
        return "quit"

    if snap.values:
        print_fn("（本局已结束）")
        return "quit"

    # 全新开局：跑开场回合
    result = ctx.graph.invoke({"campaign_id": campaign.id,
                               "branch_id": campaign.active_branch_id,
                               "turn_id": 0, "player_inputs": []}, config)
    if result.get("error") == "budget_paused":
        print_fn("本局预算已熔断暂停（budget paused）。调高上限后重新运行 play。")
        return "paused"
    for line in render_narration(result.get("narration_segments", []), ctx.module):
        print_fn(line)
    interrupts = result.get("__interrupt__")
    if not interrupts:
        print_fn("（图执行结束）")
        return "quit"
    return play_loop(ctx.graph, config, ctx.module,
                     interrupts[0].value["turn_id"], input_fn, print_fn)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ensemble", description="Ensemble 单机跑团 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="新建战役与默认角色")
    p_new.add_argument("module_path", help="模组 YAML 路径，如 ../modules/misty_hollow.yaml")
    p_new.add_argument("title", help="战役名")

    p_play = sub.add_parser("play", help="开跑 / 断点续玩")
    p_play.add_argument("campaign_id")
    p_play.add_argument("module_path")

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "new":
        ctx = assemble(settings, args.module_path)
        campaign = ctx.repo.create_campaign(ctx.module.meta.id, args.title)
        char = make_default_character(PLAYER_ID, "调查员")
        ctx.repo.append_character(campaign.id, campaign.active_branch_id, 0,
                                  char.id, asdict(char))
        print(f"战役已创建：{campaign.id}（模组 {ctx.module.meta.id}）")
        print(f"开跑：python -m app.cli play {campaign.id} {args.module_path}")
        return 0

    ctx = assemble(settings, args.module_path)
    run_play(ctx, args.campaign_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: pyproject 追加脚本入口**

`backend/pyproject.toml` 的 `[project]` 段后追加：
```toml
[project.scripts]
ensemble = "app.cli:main"
```

- [ ] **Step 5: 验证通过**

Run: `cd backend; uv run pytest tests/test_cli.py -q`
Expected: PASS（4 passed）

- [ ] **Step 6: 全量回归 + 覆盖率检查**

Run: `cd backend; uv run pytest -q; uv run pytest --cov=app --cov-report=term-missing tests/rules tests/content -q`
Expected: 全绿；rules 覆盖率 100%，content 校验器每条规则均有正/反用例

- [ ] **Step 7: 手动验收（可选，需要真实 API key）**

```powershell
$env:DASHSCOPE_API_KEY="sk-…"; $env:DEEPSEEK_API_KEY="sk-…"
cd backend
uv run python -m app.cli new ../modules/misty_hollow.yaml "雾霭镇初探"
# 记下输出的 campaign_id，然后：
uv run python -m app.cli play <campaign_id> ../modules/misty_hollow.yaml
```
验收点：① 开场叙事出现；② 输入行动（如"我向陈长老打听失踪的学徒"）后能看到检定结果与 NPC 台词（带【名字】高亮）；③ 输入"退出"结束；④ **再次 play 同一 campaign_id → 显示"读取存档，继续运行"并能继续回合（断点续玩 = M2 出口标准）**。

- [ ] **Step 8: Commit**

```bash
git add backend/app/cli.py backend/pyproject.toml backend/tests/test_cli.py
git commit -m "feat(cli): single-player loop with resume-after-restart (M2 exit)"
```

---

## 计划自审（Self-Review）

**1. 规格覆盖对照**（规格 §2-§13 → 任务映射）：

| 规格条目 | 覆盖任务 |
|---|---|
| §2 关键决策（规则/骰子/记忆/模型/内容/部署） | 2-3（规则骰子）、7-9（存储）、10-12（路由与预算）、13（记忆）、23（内容） |
| §4 回合流程 v2 | 15-21（intake→…→wait_input 全链） |
| §4.1 gm_decide 结构化输出 / 叙事有序性 | 17（决定）、18（编排）、14（`parse_segments`） |
| §4.2 TurnBuffer ↔ interrupt | **不在本计划**（api 层，M3 计划；`TurnInputs` 契约已在 Task 14 定义） |
| §4.3 场景切换链 / L2 加载时机 | 15（intake 装载 L2 快照）、16（post_turn 持久化）、19（下游只读 state） |
| §5.1 三层状态 | 14（L1）、7-9（L2）、13（L3） |
| §5.2 骰子与可复现 | 2（seed 实现）、16（DiceRecord 落库）、23（fixture 固定 seed 回放） |
| §5.3 多人可见性 | 事件层已带 `visibility`（Task 8）；过滤与推送属 M3/M4 |
| §6.1-6.3 单元划分与接口 | 文件结构 + 各任务 Interfaces；graph 只通过协议依赖（client/memory/repo 注入） |
| §7 存档语义（双源 / 续玩 / 分叉） | 续玩：21/24（checkpointer 双源）；分叉 restore API 属 M3 |
| §8 降级矩阵 | 17/21（validate）、21+22（resolve 兜底）、20/22（memory）、19（npc 静默）、18/21（narrate） |
| §9 预算熔断阶梯①-④ | 12（Guard）、15（检查点①）、20（阶梯①）、19（阶梯②）、17/18（阶梯③）、21（阶梯④） |
| §10 可观测性 | **不在本计划**（M5；usage 记账底座已在 9/11 就位） |
| §11 测试策略与覆盖率口径 | 全部任务 TDD；graph 路由/降级见 21/22；api TurnBuffer 属 M3 |
| §12 模组格式与校验 | 4-6（schema/校验/加载）、23（misty_hollow 实装） |
| §13 M1+M2 | 本计划整体范围；M3-M5 为后续计划 |

**2. 占位符扫描**：已检查全文——无 "TBD/TODO/待补/类似 Task N/适当的错误处理" 等模式；每个代码步骤均含完整代码与预期输出。

**3. 类型一致性抽查**（跨任务接口均已核对）：
- `GameState` 字段命名（Task 14）与 15-21 的读写一致；`merge_dict` 空 dict 清空语义被 `wait_input`/`fallback` 正确使用
- `LLMClient.chat(role, messages, ctx, cheap)` 与 `UsageSink.record_usage` 9 参数顺序与 `SqliteRepository.record_usage` 完全一致（`repo` 可直接作 sink）
- `BudgetGuard.check` 返回值与 `budget_level` 字符串比较（`"ok/tight/exceeded/paused"`）一致
- `SqliteRepository` 方法名（`append_state/get_state_at/append_character/list_characters_at/add_dice_record/turn_token_total/campaign_cost_total/thread_id_for`）在 15-24 中与 7-9 定义一致
- `parse_segments` 的 `Segment.speaker` 格式（`gm` / `npc:<id>`）与 18、24 的渲染一致
- `build_game_graph` 签名（21）在 23、24 的调用一致；`build_checkpointer` 在 24 复用

**4. 已知实现选择与偏差声明**：
- **NPC 子图落地方式**：独立 `StateGraph(NpcTaskState)` 子图 + 普通函数 worker 作为 Send 目标（Task 19 设计说明），规避子图状态 schema 跨版本映射差异；功能契约与规格一致
- **`misty_hollow.yaml` 归属 Task 23**（回放基线依赖它），Task 24 仅使用
- **`resolve_checks` 真异常兜底**：以 `_guarded` 包装实现规格 §8 的"真异常时失败不推进"
- 基线 fixtures 为手工编写的确定性内容；`--record` 提供真实重录通道（Task 23）

---

## 执行交接（Execution Handoff）

**Plan complete and saved to `docs/superpowers/plans/2026-09-24-ensemble-backend-core.md`（任务 1-24，全部步骤含完整代码与预期输出）。**

两种执行方式：

1. **Subagent-Driven（推荐）** —— 每个任务派发一个全新 subagent 实施，任务之间由主控审查（两阶段 review），迭代快、上下文干净；
2. **Inline Execution** —— 在当前会话内按批执行（executing-plans），带检查点批量推进。

请选择执行方式。
