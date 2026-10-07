"""FastAPI 装配：REST + WS + 会话驱动生命周期。"""
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.session import SessionManager
from app.config import Settings
from app.obs.counters import get_counters
from app.storage.repo import SqliteRepository


@dataclass
class AppDeps:
    settings: Settings
    repo: SqliteRepository
    model_factory: object | None = None   # ModelFactory；测试注入 FakeLLM 工厂
    manager: SessionManager | None = None


def create_app(deps: AppDeps) -> FastAPI:
    from app.api import routes
    from app.api import ws as ws_module

    if deps.manager is None:
        deps.manager = SessionManager(deps)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        await deps.manager.close()

    app = FastAPI(title="Ensemble", lifespan=_lifespan)
    app.state.deps = deps
    app.add_middleware(CORSMiddleware, allow_origins=deps.settings.cors_origin_list,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(routes.router)
    app.include_router(ws_module.router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics():
        snapshot = get_counters().snapshot()
        snapshot["scope"] = "process"          # 进程内计数器：重启清零，非持久化
        snapshot["usage"] = deps.repo.usage_totals()
        return snapshot

    return app
