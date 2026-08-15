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
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
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


# ── Safe managed-block writing for app-controlled Lua files ─────────────
#
# Every Lua config domain this app touches (monitors, window rules, execs,
# keybinds, ...) writes into a *named* managed block inside the shared
# provider file, and every one of those writes needs the same safety
# properties (see the migration's security requirements): a backup of the
# previous file, a write to a temp file first, `luac -p` validation of the
# *whole resulting file* when luac is available, and an atomic replace —
# never a partially written or silently invalid file. This is implemented
# once here and reused by every domain instead of duplicated per page.


class LuaWriteError(Exception):
    """Raised when a managed Lua block write is aborted before touching the
    real file — e.g. the freshly rendered content fails `luac -p`. The
    original file on disk is left completely untouched in that case."""


def _managed_block_markers(block_name: str) -> tuple[str, str]:
    return (
        f"-- BEGIN Caelestia Settings managed block: {block_name}",
        f"-- END Caelestia Settings managed block: {block_name}",
    )


def _find_managed_block(lines: list[str], block_name: str) -> tuple[int, int] | None:
    """Returns (begin_index, end_index) of the named block's marker lines,
    or None if the pair isn't present (missing, only one marker, or in the
    wrong order) — callers then treat it as "no existing block"."""
    begin, end = _managed_block_markers(block_name)
    try:
        b = next(i for i, line in enumerate(lines) if line.strip() == begin)
        e = next(i for i, line in enumerate(lines) if line.strip() == end)
    except StopIteration:
        return None
    if e <= b:
        return None
    return b, e


def managed_block_byte_range(path: Path, block_name: str) -> tuple[int, int] | None:
    """Returns the (start, end) byte offsets of the named managed block's
    *content* region in `path` — i.e. excluding the marker lines
    themselves — or None if the file or the block doesn't exist.

    Lets callers classify byte offsets found by some other scan of the
    same file (e.g. `caelestia_core.find_lua_calls`) as inside or outside
    the app-managed region, without re-implementing marker lookup.
    """
    if not path.exists():
        return None
    text = path.read_text()
    kept_lines = text.splitlines(keepends=True)
    markers = _find_managed_block([line.rstrip("\n") for line in kept_lines], block_name)
    if markers is None:
        return None
    b, e = markers
    start = sum(len(line) for line in kept_lines[: b + 1])
    end = sum(len(line) for line in kept_lines[:e])
    return start, end


def read_managed_lua_block(path: Path, block_name: str) -> list[str]:
    """Returns the lines currently inside the named managed block in
    `path`, or `[]` if the file or the block doesn't exist yet."""
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    markers = _find_managed_block(lines, block_name)
    if markers is None:
        return []
    b, e = markers
    return lines[b + 1 : e]


def write_managed_lua_block(path: Path, block_name: str, managed_lines: list[str]) -> None:
    """Replaces the named managed block in `path` with `managed_lines`,
    creating the block (and the file) if it doesn't exist yet. Content
    outside the named block — including other named blocks and any
    manually written Lua — is preserved byte-for-byte.

    Safety sequence: backup the existing file, render the full new
    content, write it to a temp file in the same directory, validate with
    `luac -p` if available, then atomically `os.replace()` it into place.
    On any failure the temp file is removed and the original file is left
    exactly as it was — this function either fully succeeds or changes
    nothing.
    """
    begin, end = _managed_block_markers(block_name)
    existing = path.read_text() if path.exists() else ""
    lines = existing.splitlines()
    markers = _find_managed_block(lines, block_name)

    block = [begin, *managed_lines, end]
    if markers is None:
        prefix = lines + ([""] if lines and lines[-1].strip() else [])
        new_lines = prefix + block
    else:
        b, e = markers
        new_lines = lines[:b] + block + lines[e + 1 :]

    new_content = "\n".join(new_lines) + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.bak_{ts}"))

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(new_content)

        luac = shutil.which("luac")
        if luac:
            result = subprocess.run([luac, "-p", str(tmp_path)], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                raise LuaWriteError(
                    t("Generated Lua is invalid, changes were not applied:") + f"\n{result.stderr.strip()}"
                )

        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def reload_hyprland() -> None:
    """Runs `hyprctl reload` — the provider-agnostic way to apply config
    file changes live (unlike `hyprctl keyword ...`, which fails outright
    under the Lua provider). Raises RuntimeError with hyprctl's own error
    output on failure; callers must surface this to the user rather than
    swallow it.
    """
    try:
        result = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"hyprctl reload: {e}") from e
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"hyprctl reload exited with code {result.returncode}")


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
