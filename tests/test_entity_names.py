"""Every entity must have a name, and both string files must agree.

This needs neither Home Assistant nor Bluetooth: the entity descriptions declare their
`translation_key` as a plain literal, so the AST is enough to list them.

It exists because of a failure mode with no error. An entity whose `translation_key` is
missing from `strings.json` does not fail to load, does not log, and does not look broken
in code review -- it just appears in the UI with no name, and only on the one instance
someone happens to look at. `en.json` is the file the frontend actually reads, so a name
added to `strings.json` alone is invisible in exactly the same way.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "soma_ble"

#: The platform file -> the section of `strings.json` its names live under.
PLATFORMS = {
    "button.py": "button",
    "number.py": "number",
    "sensor.py": "sensor",
    "binary_sensor.py": "binary_sensor",
    "switch.py": "switch",
}


def _translation_keys(filename: str) -> set[str]:
    """Every `translation_key="..."` literal in one platform file."""
    tree = ast.parse((COMPONENT / filename).read_text())
    return {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword)
        and node.arg == "translation_key"
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


@pytest.fixture(scope="module")
def strings() -> dict:
    return json.loads((COMPONENT / "strings.json").read_text())


@pytest.mark.parametrize("filename,section", sorted(PLATFORMS.items()))
def test_every_translation_key_is_named(filename: str, section: str, strings: dict) -> None:
    declared = _translation_keys(filename)
    named = set(strings["entity"].get(section, {}))
    assert declared, f"{filename} declares no translation keys -- did the file move?"
    assert declared <= named, (
        f"{filename}: no name in strings.json for {sorted(declared - named)}. "
        "Such an entity loads silently and shows up unnamed in the UI."
    )
    for key in declared:
        assert strings["entity"][section][key].get("name"), f"{section}.{key} has no name"


def test_en_json_matches_strings_json() -> None:
    """`en.json` is what the frontend reads; `strings.json` is what hassfest checks."""
    assert json.loads((COMPONENT / "translations" / "en.json").read_text()) == json.loads(
        (COMPONENT / "strings.json").read_text()
    ), "translations/en.json has drifted from strings.json"


def test_jog_is_reachable_without_developer_tools() -> None:
    """The calibration jog must exist as a BUTTON, not only as a service.

    `soma_ble.jog` is callable only from Developer Tools, which is admin-only and can be
    hidden from the sidebar -- so on some accounts a service-only jog is not reachable
    at all.
    """
    buttons = _translation_keys("button.py")
    assert {"jog_open", "jog_close"} <= buttons
    assert "jog_step" in _translation_keys("number.py")
