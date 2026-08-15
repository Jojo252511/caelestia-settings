"""Central abstraction for the Hyprland config-provider transition.

Hyprland can be configured through the legacy "hyprlang" .conf files or the
newer Lua provider (hyprland.lua and friends). `hyprctl keyword` fails under
Lua ("keyword can't work with non-legacy parsers. use eval"), so every part
of the app that talks to Hyprland config needs to know which provider is
active. This module is the single source of truth for that: persisted choice,
safe path resolution, and the one-time transitional dialog.

TODO(hyprland-lua-migration): `load_provider`/`save_provider`/
`needs_provider_prompt`/`prompt_provider_choice` exist only because Hyprland
does not yet expose a reliable way to detect the active provider
automatically (see https://github.com/Jojo252511/caelestia-settings/issues/51).
Once a reliable auto-detection method exists (e.g. parsing `hyprctl -j
version`/`hyprctl instances`), replace the persisted manual choice with
automatic detection and remove the dialog. Callers only ever go through
`resolve_path()` / `load_provider()`, so swapping the detection strategy
later needs no changes in any page.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Callable

from gi.repository import Adw

from src.config import CONFIG_DIR
from src.lang import t

PROVIDER_CONFIG_FILE = CONFIG_DIR / "hyprland_provider.json"
_PROVIDER_KEY = "hyprland_config_provider"


class Provider(str, Enum):
    """The two Hyprland config providers the app can operate against."""

    HYPRLANG = "hyprlang"
    LUA = "lua"


def load_provider() -> Provider | None:
    """Returns the persisted provider choice.

    Returns None when nothing has been chosen yet, or when the stored file
    is missing/unreadable/malformed/unrecognized. Callers MUST treat None as
    "ask the user" — never silently default to Provider.LUA or
    Provider.HYPRLANG, since guessing wrong risks editing the wrong config
    format.
    """
    if not PROVIDER_CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(PROVIDER_CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return Provider(data.get(_PROVIDER_KEY))
    except ValueError:
        return None


def save_provider(provider: Provider) -> None:
    """Persists the provider choice under CONFIG_DIR."""
    PROVIDER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROVIDER_CONFIG_FILE.write_text(json.dumps({_PROVIDER_KEY: provider.value}, indent=2))


def needs_provider_prompt() -> bool:
    """True when the transitional Yes/No dialog should be shown."""
    return load_provider() is None


# ── Path resolution ──────────────────────────────────────────────────────
# Maps each config domain to its legacy (.conf) and Lua (.lua) path. Callers
# that need the "current" path for a domain go through resolve_path(), which
# is the only place that should decide between .conf and .lua.

_HYPR_DIR = Path.home() / ".config" / "hypr"

LEGACY_PATHS: dict[str, Path] = {
    "main": _HYPR_DIR / "hyprland.conf",
    "input": _HYPR_DIR / "hyprland" / "input.conf",
    "monitors": _HYPR_DIR / "hyprland" / "monitors.conf",
    "rules": _HYPR_DIR / "hyprland" / "rules.conf",
    "keybinds": _HYPR_DIR / "hyprland" / "keybinds.conf",
    "execs": _HYPR_DIR / "hyprland" / "execs.conf",
    "variables": _HYPR_DIR / "variables.conf",
}

LUA_PATHS: dict[str, Path] = {
    "main": _HYPR_DIR / "hyprland.lua",
    "input": _HYPR_DIR / "hyprland" / "input.lua",
    "monitors": _HYPR_DIR / "hyprland" / "monitors.lua",
    "rules": _HYPR_DIR / "hyprland" / "rules.lua",
    "keybinds": _HYPR_DIR / "hyprland" / "keybinds.lua",
    "execs": _HYPR_DIR / "hyprland" / "execs.lua",
    "variables": _HYPR_DIR / "variables.lua",
}

assert set(LEGACY_PATHS) == set(LUA_PATHS), "LEGACY_PATHS and LUA_PATHS must cover the same domains"


def resolve_path(domain: str, provider: Provider) -> Path:
    """Returns the config file path for `domain` under the given provider.

    Raises KeyError for an unknown domain rather than guessing — a silently
    wrong path would risk reading or writing the wrong file.
    """
    paths = LEGACY_PATHS if provider is Provider.HYPRLANG else LUA_PATHS
    return paths[domain]


# ── Transitional dialog ──────────────────────────────────────────────────


def prompt_provider_choice(parent_window, on_chosen: Callable[[Provider], None]) -> None:
    """Shows the one-time Yes/No dialog asking which Hyprland config
    provider the user already runs Hyprland with. Only call this when
    `needs_provider_prompt()` is True. Persists the answer via
    `save_provider()` and then calls `on_chosen(provider)`.
    """
    dlg = Adw.MessageDialog(
        heading=t("Hyprland configuration format"),
        body=t(
            "Do you already use Hyprland's Lua configuration (hyprland.lua)? "
            "This is a temporary compatibility question and will be removed "
            "in a future release."
        ),
    )
    dlg.set_transient_for(parent_window)
    dlg.set_modal(True)
    dlg.add_response("no", t("No"))
    dlg.add_response("yes", t("Yes"))
    dlg.set_default_response("no")
    dlg.set_close_response("no")

    def _on_response(_dlg, response_id):
        provider = Provider.LUA if response_id == "yes" else Provider.HYPRLANG
        save_provider(provider)
        on_chosen(provider)

    dlg.connect("response", _on_response)
    dlg.present()
