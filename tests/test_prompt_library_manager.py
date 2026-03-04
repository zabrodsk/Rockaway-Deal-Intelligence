import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from agent.prompt_library import manager


@pytest.fixture()
def isolated_library(tmp_path, monkeypatch):
    library_path = tmp_path / "library.json"
    monkeypatch.setattr(manager, "LIBRARY_PATH", library_path)
    return library_path


def _item(catalog, prompt_id):
    return next(item for item in catalog["items"] if item["id"] == prompt_id)


def test_manager_loads_defaults_and_persists_updates(isolated_library):
    payload = manager.get_catalog_payload()
    assert payload["schema_version"] == 1
    assert payload["catalog"]["schema_version"] == 1
    assert len(payload["catalog"]["items"]) >= 20

    updated_catalog = deepcopy(payload["catalog"])
    market_item = _item(updated_catalog, "questions.market")
    market_item["value"] = "Custom market question?"

    saved = manager.save_catalog(updated_catalog)
    assert _item(saved["catalog"], "questions.market")["value"] == "Custom market question?"
    assert isolated_library.exists()

    raw = json.loads(isolated_library.read_text())
    assert _item(raw, "questions.market")["value"] == "Custom market question?"


def test_manager_rejects_missing_required_placeholder(isolated_library):
    catalog = manager.get_catalog()
    decomposition_user = _item(catalog, "decomposition.user")
    decomposition_user["value"] = "Only {industry} placeholder present."

    with pytest.raises(manager.PromptLibraryValidationError, match="missing required placeholder"):
        manager.save_catalog(catalog)


def test_manager_rejects_invalid_criteria_mapping_length(isolated_library):
    catalog = manager.get_catalog()
    criteria = _item(catalog, "evaluation.criteria_mapping")
    criteria["value"] = ["Only 13"] * 13

    with pytest.raises(
        manager.PromptLibraryValidationError,
        match="must contain exactly 14 items",
    ):
        manager.save_catalog(catalog)
