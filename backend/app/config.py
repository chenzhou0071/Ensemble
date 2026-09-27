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


def load_settings() -> Settings:
    return Settings(
        sqlite_path=os.environ.get("ENSEMBLE_SQLITE_PATH", "ensemble.db"),
        qwen_api_key=os.environ.get("DASHSCOPE_API_KEY"),
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY"),
    )
