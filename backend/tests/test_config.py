from pathlib import Path
from app.config import load_pricing, load_settings

def test_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    s = load_settings()
    assert s.gm_model == "qwen3.8-flash" and s.turn_window_seconds == 60
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
    s = load_settings()
    routed = {s.gm_model, s.cheap_model, s.npc_model, s.extractor_model}
    assert routed <= set(pricing.models)
