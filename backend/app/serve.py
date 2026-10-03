"""生产入口：`uvicorn app.serve:app --port 8000`（在 backend/ 目录运行）。

本地默认库为 backend/ensemble.db；可用环境变量覆盖：
ENSEMBLE_SQLITE_PATH / ENSEMBLE_MODULES_DIR / ENSEMBLE_PRICING_PATH /
DASHSCOPE_API_KEY / DEEPSEEK_API_KEY（详见 README）。
"""
from fastapi import FastAPI

from app.api.app import AppDeps, create_app
from app.config import load_settings, resolve_resource_path
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository


def build_app() -> FastAPI:
    settings = load_settings()
    # 资源路径解析：CWD 相对优先、回退仓库根（在 backend/ 下运行时 config/ 位于仓库根）
    settings.pricing_path = str(resolve_resource_path(settings.pricing_path))
    settings.modules_dir = str(resolve_resource_path(settings.modules_dir))
    engine = make_engine(settings.sqlite_path)
    init_db(engine)
    repo = SqliteRepository(engine)
    return create_app(AppDeps(settings=settings, repo=repo))


app = build_app()
