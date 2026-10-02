"""FastAPI 装配：REST + /healthz（WS/SessionManager 在 Task M3-11 挂载）。"""
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.storage.repo import SqliteRepository


@dataclass
class AppDeps:
    settings: Settings
    repo: SqliteRepository
    model_factory: object | None = None   # ModelFactory；测试注入 FakeLLM 工厂
    manager: object | None = None         # SessionManager；M3-10 后由 create_app 装配


def create_app(deps: AppDeps) -> FastAPI:
    from app.api import routes

    app = FastAPI(title="Ensemble")
    app.state.deps = deps
    app.add_middleware(CORSMiddleware, allow_origins=deps.settings.cors_origin_list,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(routes.router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
