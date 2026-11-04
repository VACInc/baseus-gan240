"""Packaging metadata checks that mirror hassfest and HACS expectations."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "baseus_gan240"


def _manifest():
    return json.loads((INTEGRATION / "manifest.json").read_text())


def test_manifest_keys_sorted_like_hassfest():
    keys = list(_manifest())
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_manifest_custom_integration_fields():
    manifest = _manifest()
    assert manifest["version"]
    assert manifest["documentation"].startswith("https://")
    assert manifest["issue_tracker"].startswith("https://")


def test_package_versions_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["version"] == _manifest()["version"]
