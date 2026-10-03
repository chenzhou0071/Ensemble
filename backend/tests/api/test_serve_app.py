"""serve.py 生产入口冒烟：工厂可构建、健康检查与模组注册表可用。"""
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]


def test_serve_app_is_built_from_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ENSEMBLE_SQLITE_PATH", str(tmp_path / "serve.db"))
    monkeypatch.setenv("ENSEMBLE_MODULES_DIR", str(ROOT / "modules"))
    monkeypatch.setenv("ENSEMBLE_PRICING_PATH", str(ROOT / "config" / "pricing.yaml"))

    from app.serve import app, build_app     # 模块级实例（uvicorn app.serve:app 的入口）

    assert build_app().title == "Ensemble"
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        ids = [m["id"] for m in client.get("/api/modules").json()]
        assert "misty_hollow" in ids


def test_build_app_resolves_default_resources_from_backend_cwd(monkeypatch, tmp_path):
    """模拟 README 启动方式（在 backend/ 下运行且不覆盖资源路径环境变量）：
    默认相对路径须能落到真实资源，否则进入房间组装会话时会报文件不存在。"""
    monkeypatch.chdir(ROOT / "backend")
    monkeypatch.setenv("ENSEMBLE_SQLITE_PATH", str(tmp_path / "backend-cwd.db"))
    monkeypatch.delenv("ENSEMBLE_MODULES_DIR", raising=False)
    monkeypatch.delenv("ENSEMBLE_PRICING_PATH", raising=False)

    from app.serve import build_app

    settings = build_app().state.deps.settings
    assert Path(settings.pricing_path).exists()   # backend/config 不存在 → 回退仓库根 config/
    assert Path(settings.modules_dir).is_dir()    # backend/../modules → 仓库根 modules/
