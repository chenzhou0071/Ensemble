from pathlib import Path
from app.config import load_pricing, load_settings, resolve_resource_path

def test_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    s = load_settings()
    assert s.gm_model == "qwen3.8-flash"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert load_settings().deepseek_api_key == "sk-test"

def test_budget_caps_env_override(monkeypatch):
    monkeypatch.delenv("ENSEMBLE_TURN_TOKEN_CAP", raising=False)
    monkeypatch.delenv("ENSEMBLE_CAMPAIGN_COST_CAP_USD", raising=False)
    s = load_settings()
    assert s.turn_token_cap == 30000 and s.campaign_cost_cap_usd == 10.0
    monkeypatch.setenv("ENSEMBLE_TURN_TOKEN_CAP", "100")
    monkeypatch.setenv("ENSEMBLE_CAMPAIGN_COST_CAP_USD", "999999")
    s2 = load_settings()
    assert s2.turn_token_cap == 100 and s2.campaign_cost_cap_usd == 999999.0

def test_enable_thinking_defaults_off_with_env_override(monkeypatch):
    monkeypatch.delenv("ENSEMBLE_ENABLE_THINKING", raising=False)
    assert load_settings().enable_thinking is False
    monkeypatch.setenv("ENSEMBLE_ENABLE_THINKING", "1")
    assert load_settings().enable_thinking is True

def test_pricing_loaded_from_yaml(tmp_path):
    p = tmp_path / "pricing.yaml"
    p.write_text("models:\n  m1: {input_per_1k: 0.001, output_per_1k: 0.002}\n", encoding="utf-8")
    pricing = load_pricing(p)
    assert pricing.models["m1"].output_per_1k == 0.002

def test_repo_pricing_covers_routed_models():
    repo_root = Path(__file__).resolve().parents[2]
    pricing = load_pricing(repo_root / "config" / "pricing.yaml")
    s = load_settings()
    routed = {s.gm_model, s.cheap_model, s.npc_model, s.extractor_model}
    assert routed <= set(pricing.models)


def test_resolve_resource_path_prefers_cwd_then_repo_root(tmp_path, monkeypatch):
    # CWD 相对优先：存在即用（返回绝对路径）
    (tmp_path / "local.yaml").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert resolve_resource_path("local.yaml") == (tmp_path / "local.yaml").resolve()
    # 找不到则回退仓库根（服务/CLI 常在 backend/ 下运行）
    repo_root = Path(__file__).resolve().parents[2]
    assert (resolve_resource_path("config/pricing.yaml")
            == (repo_root / "config" / "pricing.yaml").resolve())
