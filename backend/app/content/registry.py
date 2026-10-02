"""模组注册表：扫描目录、按 id 查找（api 层用）。"""
from pathlib import Path

import yaml


def _iter_module_files(modules_dir: str):
    return sorted(Path(modules_dir).glob("*.yaml"))


def list_modules(modules_dir: str) -> list[dict]:
    out = []
    for p in _iter_module_files(modules_dir):
        meta = yaml.safe_load(p.read_text(encoding="utf-8"))["meta"]
        out.append({"id": meta["id"], "title": meta.get("title", meta["id"]),
                    "version": str(meta.get("version", "")), "path": str(p)})
    out.sort(key=lambda m: m["id"])
    return out


def find_module_path(modules_dir: str, module_id: str) -> Path:
    for p in _iter_module_files(modules_dir):
        meta = yaml.safe_load(p.read_text(encoding="utf-8"))["meta"]
        if meta["id"] == module_id:
            return p
    raise KeyError(f"module not found: {module_id}")
