from pathlib import Path
import pytest
from app.content.loader import ModuleValidationError, load_module

FIXTURES = Path(__file__).parent.parent / "fixtures" / "modules"

def test_loads_valid_module():
    m = load_module(FIXTURES / "valid_minimal.yaml")
    assert m.meta.id == "t-min"
    assert m.npc("guard").initial_attitude == 40

def test_invalid_module_raises_with_reasons():
    with pytest.raises(ModuleValidationError) as ei:
        load_module(FIXTURES / "bad_unreachable.yaml")
    assert any("unreachable" in e for e in ei.value.errors)
