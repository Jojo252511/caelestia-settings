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

import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import caelestia_core
import gi
from enum import Enum
from pathlib import Path
from typing import Callable

gi.require_version("Adw", "1")
from gi.repository import Adw

from src.config import CONFIG_DIR
from src.lang import t

PROVIDER_CONFIG_FILE = CONFIG_DIR / "hyprland_provider.json"
_PROVIDER_KEY = "hyprland_config_provider"
LOCK_TIMEOUT_SECONDS = 2.0
LOCK_POLL_SECONDS = 0.05


class Provider(str, Enum):
    """The two Hyprland config providers the app can operate against."""

    HYPRLANG = "hyprlang"
    LUA = "lua"


class ConfigCapability(str, Enum):
    """Hyprland configuration areas with independently staged Lua support."""

    INPUT = "input"
    MONITORS = "monitors"
    WORKSPACES = "workspaces"
    WINDOW_RULES = "window-rules"
    KEYBINDS = "keybinds"
    WALLPAPER_AUTOSTART = "wallpaper-autostart"
    EXECS = "execs"


_LUA_CAPABILITIES = {
    ConfigCapability.MONITORS,
    ConfigCapability.WORKSPACES,
    ConfigCapability.WINDOW_RULES,
    ConfigCapability.INPUT,
    ConfigCapability.WALLPAPER_AUTOSTART,
    ConfigCapability.EXECS,
}

_CAPABILITY_LABELS = {
    ConfigCapability.INPUT: "General / Input",
    ConfigCapability.MONITORS: "Monitor configuration",
    ConfigCapability.WORKSPACES: "Workspace configuration",
    ConfigCapability.WINDOW_RULES: "Window Rules",
    ConfigCapability.KEYBINDS: "Keybinds",
    ConfigCapability.WALLPAPER_AUTOSTART: "Wallpaper / autostart",
    ConfigCapability.EXECS: "Execs / primary monitor",
}


class ProviderCapabilityError(RuntimeError):
    """The selected provider cannot safely serve a configuration operation."""


def capability_available(provider: Provider | None, capability: ConfigCapability) -> bool:
    if provider is Provider.HYPRLANG:
        return True
    if provider is Provider.LUA:
        return capability in _LUA_CAPABILITIES
    return False


def capability_error_message(provider: Provider | None, capability: ConfigCapability) -> str:
    if provider is None:
        return t("Choose a Hyprland configuration provider first.")
    feature = t(_CAPABILITY_LABELS[capability])
    if provider is Provider.LUA:
        return t("{feature} is not yet available for Lua configuration.").format(feature=feature)
    return t("{feature} is not available for the selected provider.").format(feature=feature)


def require_config_capability(
    capability: ConfigCapability,
    *,
    writer_provider: Provider | None = None,
) -> Provider:
    """Fail closed before a config writer performs any filesystem operation."""
    provider = load_provider()
    if not capability_available(provider, capability):
        raise ProviderCapabilityError(capability_error_message(provider, capability))
    if writer_provider is not None and provider is not writer_provider:
        raise ProviderCapabilityError(capability_error_message(provider, capability))
    return provider


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


def resolve_path(domain: str, provider: Provider | None) -> Path:
    """Returns the config file path for `domain` under the given provider.

    Raises KeyError for an unknown domain rather than guessing — a silently
    wrong path would risk reading or writing the wrong file.
    """
    if provider is Provider.HYPRLANG:
        paths = LEGACY_PATHS
    elif provider is Provider.LUA:
        paths = LUA_PATHS
    else:
        raise ValueError("A valid Hyprland configuration provider is required")
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


class ManagedBlockError(LuaWriteError):
    """The file's marker structure is ambiguous or was changed concurrently."""


class LockTimeoutError(ManagedBlockError):
    """Another settings process held the configuration lock for too long."""


def _managed_block_markers(block_name: str, comment_prefix: str = "--") -> tuple[str, str]:
    return (
        f"{comment_prefix} BEGIN Caelestia Settings managed block: {block_name}",
        f"{comment_prefix} END Caelestia Settings managed block: {block_name}",
    )


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    spans = []
    offset = 0
    for line in text.splitlines(keepends=True):
        end = offset + len(line)
        spans.append((offset, end, line.rstrip("\r\n")))
        offset = end
    if offset < len(text):
        spans.append((offset, len(text), text[offset:]))
    return spans


def _scan_managed_blocks(text: str, comment_prefix: str) -> dict[str, tuple[int, int, int, int]]:
    """Validate all markers and return full/content character ranges by name."""
    marker_prefix = re.escape(comment_prefix)
    marker_re = re.compile(
        rf"^{marker_prefix} (BEGIN|END) Caelestia Settings managed block: ([A-Za-z0-9_.-]+)$"
    )
    sentinel = f"{comment_prefix} "
    blocks = {}
    open_block = None

    for start, end, body in _line_spans(text):
        stripped = body.strip()
        if "Caelestia Settings managed block:" not in stripped:
            continue
        match = marker_re.fullmatch(stripped)
        if match is None or not stripped.startswith(sentinel):
            raise ManagedBlockError(f"Malformed managed-block marker in configuration: {stripped!r}")
        kind, name = match.groups()
        if kind == "BEGIN":
            if open_block is not None:
                raise ManagedBlockError(f"Nested managed blocks are not allowed ({open_block[0]!r}, {name!r})")
            if name in blocks:
                raise ManagedBlockError(f"Duplicate managed block: {name!r}")
            open_block = (name, start, end)
            continue
        if open_block is None:
            raise ManagedBlockError(f"Managed block ends before it begins: {name!r}")
        open_name, full_start, content_start = open_block
        if name != open_name:
            raise ManagedBlockError(f"Managed block {open_name!r} is closed by marker for {name!r}")
        blocks[name] = (full_start, end, content_start, start)
        open_block = None

    if open_block is not None:
        raise ManagedBlockError(f"Managed block has no end marker: {open_block[0]!r}")
    return blocks


def _newline_for(text: str) -> str:
    match = re.search(r"\r\n|\n|\r", text)
    return match.group(0) if match else "\n"


def _render_managed_content(
    existing: str,
    block_name: str,
    managed_lines: list[str],
    *,
    comment_prefix: str,
    legacy_marker: str | None = None,
) -> str:
    for line in managed_lines:
        if "\n" in line or "\r" in line:
            raise ManagedBlockError("Managed block entries must be individual lines")

    blocks = _scan_managed_blocks(existing, comment_prefix)
    newline = _newline_for(existing)
    begin, end = _managed_block_markers(block_name, comment_prefix)
    replacement = newline.join([begin, *managed_lines, end]) + newline

    target = blocks.get(block_name)
    if legacy_marker is not None:
        legacy_lines = [span for span in _line_spans(existing) if span[2].strip() == legacy_marker]
        if legacy_lines:
            raise ManagedBlockError(
                "Legacy start-only marker detected; explicitly migrate the old block "
                "to trusted BEGIN/END markers before saving. No changes were applied."
            )

    if target is not None:
        return existing[: target[0]] + replacement + existing[target[1] :]
    if not existing:
        return replacement
    separator = "" if existing.endswith(("\n", "\r")) else newline
    if not existing.endswith(newline * 2):
        separator += newline
    return existing + separator + replacement


def _create_backup(path: Path, original: bytes) -> Path:
    fd, backup_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.bak_")
    backup = Path(backup_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
        shutil.copystat(path, backup)
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _atomic_replace_locked(
    path: Path,
    new_content: str,
    original: bytes,
    validator: Callable[[Path], None] | None,
) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(new_content.encode("utf-8"))
        if validator is not None:
            validator(tmp_path)
        current = path.read_bytes() if path.exists() else b""
        if current != original:
            raise ManagedBlockError(f"Configuration changed concurrently: {path}")
        if path.exists():
            _create_backup(path, original)
            shutil.copystat(path, tmp_path)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _with_managed_write_lock(path: Path):
    lock_path = path.with_name(f".{path.name}.caelestia.lock")
    lock_file = open(lock_path, "a+b")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_file
        except BlockingIOError:
            if time.monotonic() >= deadline:
                lock_file.close()
                raise LockTimeoutError(
                    f"Timed out waiting for configuration write lock: {path}"
                ) from None
            time.sleep(LOCK_POLL_SECONDS)


def _rollback_and_reload(
    path: Path,
    *,
    existed: bool,
    original: bytes,
    written: bytes,
    first_error: Exception,
) -> None:
    current = path.read_bytes() if path.exists() else b""
    if current != written:
        raise ManagedBlockError(
            f"Reload failed and configuration changed concurrently; rollback aborted: {first_error}"
        ) from first_error
    if existed:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f"{path.name}.", suffix=".rollback"
        )
        rollback_tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(original)
            shutil.copystat(path, rollback_tmp)
            os.replace(rollback_tmp, path)
        except BaseException:
            rollback_tmp.unlink(missing_ok=True)
            raise
    else:
        path.unlink()
    try:
        reload_hyprland()
    except RuntimeError as rollback_reload_error:
        raise RuntimeError(
            "Reload failed; configuration was rolled back, but rollback reload also failed: "
            f"{first_error}; {rollback_reload_error}"
        ) from first_error
    raise RuntimeError(
        f"Reload failed; configuration was rolled back and reloaded: {first_error}"
    ) from first_error


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
    text = path.read_bytes().decode("utf-8")
    target = _scan_managed_blocks(text, "--").get(block_name)
    if target is None:
        return None
    return len(text[: target[2]].encode()), len(text[: target[3]].encode())


def _read_managed_block(path: Path, block_name: str, comment_prefix: str) -> list[str]:
    if not path.exists():
        return []
    text = path.read_bytes().decode("utf-8")
    target = _scan_managed_blocks(text, comment_prefix).get(block_name)
    if target is None:
        return []
    return text[target[2] : target[3]].splitlines()


def read_managed_lua_block(path: Path, block_name: str) -> list[str]:
    """Returns the lines currently inside the named managed block in
    `path`, or `[]` if the file or the block doesn't exist yet."""
    return _read_managed_block(path, block_name, "--")


def read_managed_legacy_block(path: Path, block_name: str) -> list[str]:
    """Returns the lines currently inside the named managed block in a
    legacy (`#`-comment) `path`, or `[]` if the file or the block doesn't
    exist yet. Mirrors `read_managed_lua_block` for the hyprlang provider —
    used by callers (e.g. reading back the app-owned primary-monitor exec
    entry) that must not scan the whole file, since a legacy config file
    like execs.conf can also hold manually written, non-app-owned content
    outside the named block."""
    return _read_managed_block(path, block_name, "#")


# ── Competing foreign-content detection ──────────────────────────────────
#
# A managed block is only ever compared against ITS OWN previous content
# (byte-for-byte preservation of everything else) — but that alone can't
# tell a caller whether some OTHER, foreign entry in the same file
# independently controls the same real-world effect (e.g. a second
# manually written `exec-once = mpvpaper ...` line, or a second
# `xrandr --primary` handler). Hyprland runs every `exec-once`/
# `hl.exec_cmd` autostart entry it finds, not just the last one, so a
# foreign entry like that isn't overridden by this app's own managed
# block — it competes with it. These helpers let a caller detect that
# situation so it can fail closed (writing) or show a neutral/undetermined
# state (reading) instead of silently claiming its own value is the only
# one that matters. Neither helper ever mutates anything they scan.


def find_lines_outside_managed_blocks(
    text: str, block_names: list[str], comment_prefix: str
) -> list[str]:
    """Returns every non-blank line in `text` that falls outside ALL of
    the named managed blocks — content this app does not own. For legacy
    (`#`-comment) files only, where every entry of interest is always a
    single line; Lua callers should use
    `find_competing_lua_autostart_entries` instead, since a foreign Lua
    call can span multiple lines."""
    blocks = _scan_managed_blocks(text, comment_prefix)
    own_ranges = [blocks[name][:2] for name in block_names if name in blocks]
    result = []
    for start, end, body in _line_spans(text):
        if not body.strip():
            continue
        if any(r_start <= start < r_end for r_start, r_end in own_ranges):
            continue
        result.append(body)
    return result


def find_competing_lua_autostart_entries(
    text: str, own_block_names: list[str], relevant: Callable[[str], bool]
) -> list[str]:
    """Scans `text` for `hl.on(...)` registrations that mention
    "hyprland.start" and fall OUTSIDE all of `own_block_names`, using
    `caelestia_core.find_lua_calls` (tolerates arbitrary surrounding Lua,
    including multi-line calls, and never raises on unparseable content).
    Each candidate is strictly parsed via `caelestia_core.parse_autostart_cmd`;
    ones that parse and whose command satisfies `relevant` are returned as
    a match, and so is any candidate that FAILS to parse — a shape this
    codec can't verify one way or the other must never be silently
    ignored, since it could still be a competing dynamic override this
    codec simply can't evaluate. Returns the raw matched Lua source text
    of every match; never mutates `text`."""
    blocks = _scan_managed_blocks(text, "--")
    own_ranges = [blocks[name][:2] for name in own_block_names if name in blocks]
    matches = []
    for start, end, match_text in caelestia_core.find_lua_calls(text, "hl.on"):
        if any(r_start <= start < r_end for r_start, r_end in own_ranges):
            continue
        if "hyprland.start" not in match_text:
            continue
        try:
            cmd = caelestia_core.parse_autostart_cmd(match_text)
        except ValueError:
            matches.append(match_text)
            continue
        if relevant(cmd):
            matches.append(match_text)
    return matches


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
    luac = shutil.which("luac")
    if luac is None:
        raise LuaWriteError(t("Lua compiler (luac) is required; changes were not applied."))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _with_managed_write_lock(path):
        original = path.read_bytes() if path.exists() else b""
        existing = original.decode("utf-8")
        new_content = _render_managed_content(
            existing, block_name, managed_lines, comment_prefix="--"
        )

        def validate(tmp_path: Path) -> None:
            result = subprocess.run([luac, "-p", str(tmp_path)], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                raise LuaWriteError(
                    t("Generated Lua is invalid, changes were not applied:") + f"\n{result.stderr.strip()}"
                )

        _atomic_replace_locked(path, new_content, original, validate)


def write_managed_lua_block_and_reload(
    path: Path,
    block_name: str,
    managed_lines: list[str],
    *,
    pre_write_check: Callable[[str], None] | None = None,
) -> None:
    """Commit a validated block, reload, and roll back plus reload again on failure.

    `pre_write_check`, if given, is called once inside the write lock with
    the exact existing file text about to be transformed — right before
    it is transformed — and may raise to abort the write (no temp file,
    no backup, no reload) with the file left completely untouched.
    Callers use this for checks that must see the exact bytes the write
    is based on, not a possibly-stale pre-lock read (e.g. detecting a
    competing manually written autostart entry outside this block).
    """
    luac = shutil.which("luac")
    if luac is None:
        raise LuaWriteError(t("Lua compiler (luac) is required; changes were not applied."))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _with_managed_write_lock(path):
        existed = path.exists()
        original = path.read_bytes() if existed else b""
        existing_text = original.decode("utf-8")
        if pre_write_check is not None:
            pre_write_check(existing_text)
        new_content = _render_managed_content(
            existing_text, block_name, managed_lines, comment_prefix="--"
        )

        def validate(tmp_path: Path) -> None:
            result = subprocess.run([luac, "-p", str(tmp_path)], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                raise LuaWriteError(
                    t("Generated Lua is invalid, changes were not applied:") + f"\n{result.stderr.strip()}"
                )

        _atomic_replace_locked(path, new_content, original, validate)
        try:
            reload_hyprland()
        except RuntimeError as first_error:
            _rollback_and_reload(
                path,
                existed=existed,
                original=original,
                written=new_content.encode("utf-8"),
                first_error=first_error,
            )


def update_managed_lua_block_and_reload(
    path: Path,
    block_name: str,
    transform: Callable[[list[str]], list[str]],
    *,
    verify: Callable[[], None] | None = None,
) -> None:
    """Like write_managed_lua_block_and_reload, but takes a pure
    `transform` callback instead of the new content directly. `transform`
    receives the block's CURRENT content — read fresh, under the same
    lock, from the exact original bytes about to be replaced — and must
    return the new content.

    This closes a TOCTOU race a caller would otherwise have if it read
    the block's current content itself *before* acquiring the lock:
    another writer could change the file in between, and the caller's
    stale read would silently clobber that change when it finally writes.
    Because `transform` only ever sees content read after the lock is
    held, whatever it returns is always based on the latest state on
    disk. `transform` must be pure — no file I/O of its own, and it must
    not try to acquire the same lock (no nested locking; see
    `_with_managed_write_lock`, which is not reentrant and would just
    time out against itself).

    `verify`, if given, is called once immediately after a successful
    reload. If it raises ANY `Exception` — not just `RuntimeError`; a
    verifier is caller-supplied and may fail with `ValueError`,
    `TypeError`, or anything else, e.g. because the reloaded
    configuration's live, observed effect doesn't match what was just
    written (a later manual entry elsewhere in the file could still be
    taking priority) — the write is treated exactly like a failed reload:
    the file is rolled back to its previous bytes and reloaded a second
    time, and the original error propagates. This lets a caller confirm a
    write actually took effect, not just that Hyprland accepted the
    config syntactically, under the same transaction and lock as the
    write itself. `BaseException` subclasses that aren't `Exception`
    (`KeyboardInterrupt`, `SystemExit`, ...) are deliberately NOT caught
    here — they propagate immediately, without a rollback attempt, exactly
    like any other unguarded code in this process.
    """
    luac = shutil.which("luac")
    if luac is None:
        raise LuaWriteError(t("Lua compiler (luac) is required; changes were not applied."))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _with_managed_write_lock(path):
        existed = path.exists()
        original = path.read_bytes() if existed else b""
        existing_text = original.decode("utf-8")
        current_block = _scan_managed_blocks(existing_text, "--").get(block_name)
        current_lines = (
            existing_text[current_block[2] : current_block[3]].splitlines()
            if current_block is not None
            else []
        )
        managed_lines = transform(current_lines)
        new_content = _render_managed_content(
            existing_text, block_name, managed_lines, comment_prefix="--"
        )

        def validate(tmp_path: Path) -> None:
            result = subprocess.run([luac, "-p", str(tmp_path)], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                raise LuaWriteError(
                    t("Generated Lua is invalid, changes were not applied:") + f"\n{result.stderr.strip()}"
                )

        _atomic_replace_locked(path, new_content, original, validate)
        try:
            reload_hyprland()
            if verify is not None:
                verify()
        except Exception as first_error:
            _rollback_and_reload(
                path,
                existed=existed,
                original=original,
                written=new_content.encode("utf-8"),
                first_error=first_error,
            )


def write_managed_legacy_block_and_reload(
    path: Path,
    block_name: str,
    managed_lines: list[str],
    *,
    legacy_marker: str | None = None,
    legacy_predicate: Callable[[str], bool] | None = None,
    pre_write_check: Callable[[str], None] | None = None,
) -> None:
    """Atomically write a legacy block, reload, and roll back on reload failure.

    `legacy_marker`, if given, fails closed when an old *start-only*
    marker comment (a whole line this app used to write on its own,
    before the BEGIN/END scheme existed) is still present anywhere in the
    file — the caller must migrate it manually first.

    `legacy_predicate`, if given, fails closed when a line OUTSIDE every
    already-existing managed block matches the predicate — for content
    this app itself used to write inline (e.g. a fixed sentinel comment
    appended to a generated line) with no dedicated block structure at
    all, so there is no single fixed marker line to match against.
    Unlike `legacy_marker`, this never looks inside an existing managed
    block (new content this app itself just wrote there would otherwise
    always match).

    Both `legacy_marker` and `legacy_predicate` are checked twice: once
    here, before the lock is even acquired (a cheap early-out for the
    common case), and again inside the lock against the EXACT bytes about
    to be transformed. The first check alone would leave a TOCTOU window
    open — another writer could introduce exactly the content the
    predicate is guarding against in the gap between this check and lock
    acquisition — so only the in-lock recheck is actually load-bearing;
    the pre-lock one is purely a fast path that avoids paying for
    `mkdir`/lock acquisition on the common "nothing to detect" case.

    `pre_write_check`, if given, is called once inside the lock — after
    the in-lock legacy recheck, on the same exact bytes — and may raise
    to abort the write with the file left completely untouched. See
    `write_managed_lua_block_and_reload` for the same parameter.
    """

    def _check_legacy(existing: str) -> None:
        if legacy_marker is not None and any(
            span[2].strip() == legacy_marker for span in _line_spans(existing)
        ):
            raise ManagedBlockError(
                "Legacy start-only marker detected; explicitly migrate the old block "
                "to trusted BEGIN/END markers before saving. No changes were applied."
            )
        if legacy_predicate is not None:
            managed_ranges = list(_scan_managed_blocks(existing, "#").values())
            for start, end, body in _line_spans(existing):
                if any(r_start <= start < r_end for r_start, r_end, _, _ in managed_ranges):
                    continue
                if legacy_predicate(body.strip()):
                    raise ManagedBlockError(
                        "Manually written configuration matches this app's legacy managed "
                        "content outside a managed block; migrate it manually before saving. "
                        "No changes were applied."
                    )

    if path.exists():
        _check_legacy(path.read_bytes().decode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _with_managed_write_lock(path):
        existed = path.exists()
        original = path.read_bytes() if existed else b""
        existing_text = original.decode("utf-8")
        _check_legacy(existing_text)
        if pre_write_check is not None:
            pre_write_check(existing_text)
        new_content = _render_managed_content(
            existing_text,
            block_name,
            managed_lines,
            comment_prefix="#",
            legacy_marker=legacy_marker,
        )
        _atomic_replace_locked(path, new_content, original, None)
        try:
            reload_hyprland()
        except RuntimeError as first_error:
            _rollback_and_reload(
                path,
                existed=existed,
                original=original,
                written=new_content.encode("utf-8"),
                first_error=first_error,
            )


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
    dlg.set_close_response("cancel")

    def _on_response(_dlg, response_id):
        if response_id not in {"yes", "no"}:
            return
        provider = Provider.LUA if response_id == "yes" else Provider.HYPRLANG
        save_provider(provider)
        on_chosen(provider)

    dlg.connect("response", _on_response)
    dlg.present()
