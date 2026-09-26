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
