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
    gm_model: str = "qwen3.8-flash"
    cheap_model: str = "qwen3.8-flash"
    npc_model: str = "deepseek-flash"
    extractor_model: str = "qwen3.8-flash"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    qwen_api_key: str | None = None
    deepseek_api_key: str | None = None
    request_timeout_seconds: int = 60
    turn_window_seconds: int = 60
    turn_token_cap: int = 30000
    campaign_cost_cap_usd: float = 10.0
    enable_thinking: bool = False   # qwen 系思考模式：要快+省，默认关（ENSEMBLE_ENABLE_THINKING=1 开启）
    modules_dir: str = "../modules"
    cors_origins: str = "http://localhost:5173"
    single_player_debounce_seconds: float = 2.0
    ws_replay_size: int = 500

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def load_settings() -> Settings:
    return Settings(
        sqlite_path=os.environ.get("ENSEMBLE_SQLITE_PATH", "ensemble.db"),
        pricing_path=os.environ.get("ENSEMBLE_PRICING_PATH", "config/pricing.yaml"),
        qwen_api_key=os.environ.get("DASHSCOPE_API_KEY"),
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY"),
        modules_dir=os.environ.get("ENSEMBLE_MODULES_DIR", "../modules"),
        turn_token_cap=int(os.environ.get("ENSEMBLE_TURN_TOKEN_CAP", "30000")),
        campaign_cost_cap_usd=float(os.environ.get("ENSEMBLE_CAMPAIGN_COST_CAP_USD", "10.0")),
        enable_thinking=os.environ.get("ENSEMBLE_ENABLE_THINKING", "").lower() in ("1", "true"),
    )
