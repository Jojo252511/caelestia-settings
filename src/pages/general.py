import json
import re
import shutil
import subprocess
import caelestia_core
from gi.repository import Gtk, Adw
from src.config import HYPR_INPUT_CONF
from src.hypr_provider import (
    ConfigCapability,
    Provider,
    capability_available,
    load_provider,
    managed_block_byte_range,
    read_managed_lua_block,
    require_config_capability,
    resolve_path,
    update_managed_lua_block_and_reload,
)
from src.lang import t

INPUT_LUA_BLOCK = "input"

# Gängige Tastaturlayouts: (xkb-Code, Anzeigename)
KEYBOARD_LAYOUTS = [
    ("ad",  "Andorranisch"),
    ("af",  "Afghanisch"),
    ("al",  "Albanisch"),
    ("am",  "Armenisch"),
    ("ara", "Arabisch"),
    ("at",  "Österreichisch (AT)"),
    ("au",  "Australisch"),
    ("az",  "Aserbaidschanisch"),
    ("ba",  "Bosnisch"),
    ("bd",  "Bengalisch"),
    ("be",  "Belgisch"),
    ("bg",  "Bulgarisch"),
    ("br",  "Brasilianisch"),
    ("brai","Braille"),
    ("bt",  "Bhutanisch"),
    ("bw",  "Botswanisch"),
    ("by",  "Weißrussisch"),
    ("ca",  "Kanadisch"),
    ("cd",  "Kongolesisch (DR)"),
    ("ch",  "Schweizer"),
    ("cm",  "Kamerunisch"),
    ("cn",  "Chinesisch"),
    ("cz",  "Tschechisch"),
    ("de",  "Deutsch (DE)"),
    ("dk",  "Dänisch"),
    ("ee",  "Estnisch"),
    ("epo", "Esperanto"),
    ("es",  "Spanisch"),
    ("et",  "Äthiopisch"),
    ("eu",  "Baskisch"),
    ("fi",  "Finnisch"),
    ("fo",  "Färöisch"),
    ("fr",  "Französisch"),
    ("gb",  "Englisch (UK)"),
    ("ge",  "Georgisch"),
    ("gh",  "Ghanaisch"),
    ("gn",  "Guineisch"),
    ("gr",  "Griechisch"),
    ("hr",  "Kroatisch"),
    ("hu",  "Ungarisch"),
    ("ie",  "Irisch"),
    ("il",  "Hebräisch"),
    ("in",  "Indisch"),
    ("iq",  "Irakisch"),
    ("ir",  "Persisch"),
    ("is",  "Isländisch"),
    ("it",  "Italienisch"),
    ("jp",  "Japanisch"),
    ("ke",  "Kenianisch"),
    ("kg",  "Kirgisisch"),
    ("kh",  "Khmerisch"),
    ("kr",  "Koreanisch"),
    ("kz",  "Kasachisch"),
    ("la",  "Laotisch"),
    ("latam","Lateinamerikanisch"),
    ("lk",  "Singhalesisch"),
    ("lt",  "Litauisch"),
    ("lv",  "Lettisch"),
    ("ma",  "Marokkanisch"),
    ("mao", "Maori"),
    ("md",  "Moldauisch"),
    ("me",  "Montenegrinisch"),
    ("mk",  "Mazedonisch"),
    ("ml",  "Malisch"),
    ("mm",  "Myanmarisch"),
    ("mn",  "Mongolisch"),
    ("mt",  "Maltesisch"),
    ("mv",  "Maledivisch"),
    ("my",  "Malaysisch"),
    ("ng",  "Nigerianisch"),
    ("nl",  "Niederländisch"),
    ("no",  "Norwegisch"),
    ("np",  "Nepalesisch"),
    ("ph",  "Philippinisch"),
    ("pk",  "Pakistanisch"),
    ("pl",  "Polnisch"),
    ("pt",  "Portugiesisch"),
    ("ro",  "Rumänisch"),
    ("rs",  "Serbisch"),
    ("ru",  "Russisch"),
    ("se",  "Schwedisch"),
    ("si",  "Slowenisch"),
    ("sk",  "Slowakisch"),
    ("sn",  "Senegalesisch"),
    ("sy",  "Syrisch"),
    ("tg",  "Togoisch"),
    ("th",  "Thaiisch"),
    ("tj",  "Tadschikisch"),
    ("tm",  "Turkmenisch"),
    ("tr",  "Türkisch"),
    ("tw",  "Taiwanisch"),
    ("tz",  "Tansanisch"),
    ("ua",  "Ukrainisch"),
    ("us",  "Englisch (US)"),
    ("uz",  "Usbekisch"),
    ("vn",  "Vietnamesisch"),
    ("za",  "Südafrikanisch"),
]

_PROVIDER_UNSET = object()


# ── Lua provider ──────────────────────────────────────────────────────────
#
# input.lua may contain manual, hand-written hl.config({ input = {...} })
# calls anywhere in the file — single- or multi-line, mixed with comments,
# other top-level sections (general, decoration, ...), other input fields
# this app doesn't own (touchpad, sensitivity, ...), and possibly more than
# one hl.config(...) call with dynamic (vars.foo) or otherwise unparsebable
# values. A static value from an EARLIER call must never be shown as the
# "current" value once a LATER call could plausibly have overridden it with
# something this codec can't evaluate — that would show a guess, not a
# fact. Only Hyprland itself reliably knows which call actually took
# effect, so the EFFECTIVE value shown to the user comes from Hyprland's
# own live-resolved state (`hyprctl -j getoption`), never from statically
# picking a "winning" call ourselves. `hyprctl` unreachable, non-zero, or
# an unexpected/ambiguous JSON shape all mean "unknown" — never a guessed
# default.
#
# Static file parsing (_merge_static_input_calls) is still used, but only
# for a narrower, safe purpose: reading back the app's OWN previously
# written managed-block content at write time, so a partial update (only
# one of the two fields changing) can preserve the other field's
# already-app-managed value without adopting or guessing anything.


def _merge_static_input_calls(text: str) -> dict:
    """Scans `text` for every hl.config({ input = {...} }) call and returns
    the last statically-known value per input field, in file order — later
    static assignments win. A call that fails to parse at all (e.g. it
    contains a dynamic value like vars.foo anywhere in its argument tree)
    contributes nothing for ANY field, including ones it might have held a
    literal value for — this codec has no partial-parse recovery within a
    single call (see rust/caelestia-core/src/lua.rs), so such a call must
    never be silently skipped as if it didn't exist. This is used only for
    the app's OWN managed-block content (see module docstring above), where
    every call is one this app itself wrote — never for determining an
    "effective" value shown to the user."""
    result: dict = {}
    for _start, _end, call_text in caelestia_core.find_lua_calls(text, "hl.config"):
        try:
            call_path, args = caelestia_core.parse_lua_call(call_text)
        except ValueError:
            continue
        if call_path != "hl.config" or not args or not isinstance(args[0], dict):
            continue
        input_table = args[0].get("input")
        if not isinstance(input_table, dict):
            continue
        if isinstance(input_table.get("kb_layout"), str):
            result["kb_layout"] = input_table["kb_layout"]
        if isinstance(input_table.get("numlock_by_default"), bool):
            result["numlock_by_default"] = input_table["numlock_by_default"]
    return result


def _read_own_managed_input_fields() -> dict:
    """Native-typed {kb_layout, numlock_by_default} currently inside the
    app's own "input" managed block only (not the whole file) — a
    point-in-time read for introspection/tests. Propagates
    ManagedBlockError if the block's own marker structure is corrupted,
    rather than silently ignoring it. NOT used by the writer itself (see
    update_managed_lua_block_and_reload's `transform` in
    _write_input_lua_field): reading here and using the result in a
    separate, later write would be a TOCTOU race against a concurrent
    writer touching the same block."""
    path = resolve_path("input", Provider.LUA)
    lines = read_managed_lua_block(path, INPUT_LUA_BLOCK)
    if not lines:
        return {}
    return _merge_static_input_calls("\n".join(lines))


def _hyprctl_getoption(option: str) -> dict | None:
    """Read-only `hyprctl -j getoption <option>`, returning the parsed JSON
    object or None if hyprctl is missing, unreachable, times out, exits
    non-zero, or doesn't return a JSON object — any of which mean "can't
    safely determine this", never a reason to guess or raise."""
    hyprctl = shutil.which("hyprctl")
    if hyprctl is None:
        return None
    try:
        result = subprocess.run(
            [hyprctl, "-j", "getoption", option], capture_output=True, text=True, timeout=3
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _get_effective_kb_layout() -> str | None:
    """Hyprland's own live-resolved input:kb_layout, or None if it can't
    be determined safely — never a guessed default like "us"."""
    data = _hyprctl_getoption("input:kb_layout")
    if data is None:
        return None
    value = data.get("str")
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _get_effective_numlock() -> bool | None:
    """Hyprland's own live-resolved input:numlock_by_default, or None if
    it can't be determined safely — never a guessed default like False.
    Hyprland reports bool config values as 0/1 under "int" in getoption's
    JSON, not as a JSON boolean."""
    data = _hyprctl_getoption("input:numlock_by_default")
    if data is None:
        return None
    value = data.get("int")
    if value == 0:
        return False
    if value == 1:
        return True
    return None


def _read_input_lua() -> dict:
    """Effective input.kb_layout / input.numlock_by_default as strings,
    matching the legacy dict contract of read_input_conf(). Sourced from
    Hyprland's own live state (see module docstring above) — a field is
    simply absent when it can't be safely determined; callers must not
    guess a default on its behalf."""
    path = resolve_path("input", Provider.LUA)
    if path.exists():
        # Validates the app's own managed-block marker structure as a
        # side effect (raises ManagedBlockError on corruption) — even
        # though the displayed value below no longer depends on this
        # block's content, a broken app-owned block must still be a
        # visible, fail-closed error rather than silently ignored, since
        # future writes rely on this structure being intact.
        managed_block_byte_range(path, INPUT_LUA_BLOCK)
    result = {}
    layout = _get_effective_kb_layout()
    if layout is not None:
        result["kb_layout"] = layout
    numlock = _get_effective_numlock()
    if numlock is not None:
        result["numlock_by_default"] = "true" if numlock else "false"
    return result


def _validate_input_field(key: str, value) -> None:
    """Fails fast with ValueError before ANY path resolution, capability
    check, lock, backup, temp file, write, luac, or reload. Python's bool
    is an int subclass, but isinstance(value, str) and
    isinstance(value, bool) are each still exact for what they check here
    — isinstance(1, bool) is False (1 is an int instance, not a bool
    instance) and isinstance(True, str) is False — so 0/1/"true" are all
    correctly rejected for numlock_by_default, and True/False are
    correctly rejected for kb_layout."""
    if key == "kb_layout":
        if not isinstance(value, str):
            raise ValueError(f"kb_layout must be a string, got {type(value).__name__}")
        if not value.strip():
            raise ValueError("kb_layout must be a non-empty, non-whitespace string")
    elif key == "numlock_by_default":
        if not isinstance(value, bool):
            raise ValueError(f"numlock_by_default must be a bool, got {type(value).__name__}")
    else:
        raise ValueError(f"unknown input field: {key!r}")


def _write_input_lua_field(key: str, value) -> None:
    """Sets a single input.* field (kb_layout: non-empty str,
    numlock_by_default: bool) in the app's managed hl.config({...}) call
    inside input.lua.

    - Validates key/value strictly before any side effect (see
      _validate_input_field).
    - Preserves the OTHER field's value by reading it from the exact same
      locked, freshly-read bytes the write is about to replace (via
      update_managed_lua_block_and_reload's `transform`) — never from an
      earlier, separately-timed read, which would risk losing a
      concurrent writer's change to that field.
    - After a successful write and reload, verifies the change actually
      took effect (hyprctl's own live-resolved value now matches) before
      letting the caller treat this as success; a later manual override
      elsewhere in the file could otherwise silently win. A failed
      verification is treated exactly like a failed reload: the file is
      rolled back and reloaded again, and the error propagates.
    """
    _validate_input_field(key, value)
    require_config_capability(ConfigCapability.INPUT, writer_provider=Provider.LUA)
    path = resolve_path("input", Provider.LUA)

    def transform(current_lines: list[str]) -> list[str]:
        fields = _merge_static_input_calls("\n".join(current_lines))
        fields[key] = value
        ordered = {}
        if "kb_layout" in fields:
            ordered["kb_layout"] = fields["kb_layout"]
        if "numlock_by_default" in fields:
            ordered["numlock_by_default"] = fields["numlock_by_default"]
        return [caelestia_core.render_lua_call("hl.config", [{"input": ordered}])]

    def verify() -> None:
        effective = _get_effective_kb_layout() if key == "kb_layout" else _get_effective_numlock()
        if effective != value:
            raise RuntimeError(
                t(
                    "{field} was written and Hyprland reloaded, but the change is not "
                    "effective — a later configuration entry may be overriding it."
                ).format(field=key)
            )

    update_managed_lua_block_and_reload(path, INPUT_LUA_BLOCK, transform, verify=verify)


def read_input_conf(provider: Provider | None | object = _PROVIDER_UNSET) -> dict:
    """Liest input.conf und gibt ein Dict mit allen key=value zurück."""
    result = {}
    if provider is _PROVIDER_UNSET:
        provider = load_provider()
    if not capability_available(provider, ConfigCapability.INPUT):
        return result
    if provider is Provider.LUA:
        return _read_input_lua()
    if not HYPR_INPUT_CONF.exists():
        return result
    try:
        # Einfacher Parser der auch verschachtelte Blöcke ignoriert
        content = HYPR_INPUT_CONF.read_text()
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "{" in line or "}" in line:
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    except Exception as e:
        print(f"input.conf lesen fehler: {e}")
    return result


def _write_input_conf_key(key: str, value: str):
    """Ersetzt einen Schlüssel in input.conf. Schreibt ihn ans Ende wenn nicht gefunden."""
    require_config_capability(ConfigCapability.INPUT, writer_provider=Provider.HYPRLANG)
    if not HYPR_INPUT_CONF.exists():
        return
    try:
        content = HYPR_INPUT_CONF.read_text()
        pattern = rf"^(\s*{re.escape(key)}\s*=\s*).*"
        new_line = rf"\g<1>{value}"
        new_content, n = re.subn(pattern, new_line, content, flags=re.MULTILINE)
        if n == 0:
            # Schlüssel nicht gefunden — innerhalb des input {}-Blocks einfügen
            new_content = re.sub(
                r"(input\s*\{[^}]*)",
                rf"\1    {key} = {value}\n",
                content,
                count=1,
                flags=re.DOTALL,
            )
        HYPR_INPUT_CONF.write_text(new_content)
    except Exception as e:
        raise RuntimeError(f"input.conf schreiben fehler: {e}") from e


class GeneralPage(Gtk.Box):
    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.main_window = main_window
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        self.is_loading = False

        # ── EINGABE ──────────────────────────────────────────────────────
        input_group = Adw.PreferencesGroup(title=t("Input"))
        self.append(input_group)

        # Tastaturlayout-Dropdown
        layout_row = Adw.ActionRow(title=t("Keyboard Layout"))
        layout_row.set_subtitle(t("Live change in Hyprland"))

        self.layout_combo = Gtk.ComboBoxText()
        self.layout_combo.set_valign(Gtk.Align.CENTER)

        # Suchfunktion via Gtk.ComboBox hat keinen eingebauten Filter —
        # wir nutzen ein Entry-Completion-ähnliches Dropdown
        for code, label in KEYBOARD_LAYOUTS:
            self.layout_combo.append(code, f"{label}  ({code})")

        layout_row.add_suffix(self.layout_combo)
        input_group.add(layout_row)

        # NumLock
        self.numlock_row = Adw.SwitchRow(
            title=t("NumLock on startup"),
            subtitle=t("Live change in Hyprland"),
        )
        input_group.add(self.numlock_row)

        # ── REGION & SPRACHE ─────────────────────────────────────────────
        system_group = Adw.PreferencesGroup(title=t("Region and Language"))
        self.append(system_group)

        lang_row = Adw.ActionRow(title=t("System Language"))
        lang_row.set_subtitle(t("Requires password"))
        self.lang_combo = Gtk.ComboBoxText()
        self.lang_combo.append("de_DE.UTF-8", "Deutsch (Deutschland)")
        self.lang_combo.append("en_US.UTF-8", "English (US)")
        self.lang_combo.append("en_GB.UTF-8", "English (UK)")
        lang_row.add_suffix(self.lang_combo)
        system_group.add(lang_row)

        time_row = Adw.ActionRow(title=t("Timezone"))
        self.time_combo = Gtk.ComboBoxText()
        self.time_combo.append("Europe/Berlin",   "Berlin (CET/CEST)")
        self.time_combo.append("Europe/London",   "London (GMT/BST)")
        self.time_combo.append("America/New_York","New York (EST/EDT)")
        self.time_combo.append("UTC",             "UTC")
        time_row.add_suffix(self.time_combo)
        system_group.add(time_row)

        # Laden & Signale
        self.load_if_available(load_provider())
        self.layout_combo.connect("changed",        self._on_layout_changed)
        self.numlock_row.connect("notify::active",  self._on_numlock_changed)
        self.lang_combo.connect("changed",          self._on_language_changed)
        self.time_combo.connect("changed",          self._on_timezone_changed)

    # ── Laden ─────────────────────────────────────────────────────────────

    def _set_neutral_state(self):
        self.is_loading = True
        try:
            self.layout_combo.set_active(-1)
            self.numlock_row.set_active(False)
            self.lang_combo.set_active(-1)
            self.time_combo.set_active(-1)
        finally:
            self.is_loading = False

    def load_if_available(self, provider: Provider | None) -> bool:
        if not capability_available(provider, ConfigCapability.INPUT):
            self._set_neutral_state()
            return False
        try:
            self._load_all(provider)
        except Exception as e:
            # _load_all() is written to handle its own errors internally
            # (see its own try/finally below) — this is a last-resort
            # backstop so a bug there still can't escape into GTK
            # construction or a provider-change callback.
            self._set_neutral_state()
            self.show_toast(f"{t('Error:')} {e}")
            return False
        return True

    def on_provider_changed(self, provider: Provider | None):
        self.load_if_available(provider)

    def _apply_layout_and_numlock(self, conf: dict) -> None:
        """Applies a read_input_conf()-shaped dict to the two Lua/Hyprlang-
        backed widgets. A missing key means the value is genuinely unknown
        (not "us" / not-set) and shows as no selection / off rather than a
        guessed default — see the module-level Lua-provider notes above
        for why the value can be unknown even when the file itself
        exists."""
        layout = conf.get("kb_layout")
        if layout:
            layout = layout.lower()
            if not self.layout_combo.set_active_id(layout):
                # Unbekanntes Layout ans Ende anhängen
                self.layout_combo.append(layout, f"Unbekannt  ({layout})")
                self.layout_combo.set_active_id(layout)
        else:
            self.layout_combo.set_active(-1)

        numlock_val = conf.get("numlock_by_default")
        self.numlock_row.set_active(numlock_val == "true")

    def _revert_input_display(self) -> None:
        """Restores the layout combo / numlock switch to the current
        safe/effective value after a failed write, under a suppressed
        `is_loading` guard so this doesn't trigger another write via the
        widgets' own change signals. Falls back to neutral (no selection /
        off) if the safe value itself can't be determined right now."""
        self.is_loading = True
        try:
            try:
                conf = read_input_conf()
            except Exception:
                conf = {}
            self._apply_layout_and_numlock(conf)
        finally:
            self.is_loading = False

    def _load_all(self, provider: Provider | None | object = _PROVIDER_UNSET):
        self.is_loading = True
        try:
            try:
                if provider is _PROVIDER_UNSET:
                    provider = load_provider()
                if not capability_available(provider, ConfigCapability.INPUT):
                    self._set_neutral_state()
                    return

                try:
                    conf = read_input_conf(provider)
                except Exception as e:
                    # A corrupted managed block (or any other read
                    # failure) must be a visible, fail-closed neutral
                    # state — never a silently stale/guessed display, and
                    # never an exception escaping page load.
                    conf = {}
                    self.show_toast(f"{t('Error:')} {e}")

                self._apply_layout_and_numlock(conf)

                # Systemsprache
                try:
                    res = subprocess.run(["localectl", "status"], capture_output=True, text=True)
                    for line in res.stdout.splitlines():
                        if "LANG=" in line:
                            lang = line.split("LANG=")[1].strip()
                            if not self.lang_combo.set_active_id(lang):
                                self.lang_combo.append(lang, f"{t('Current')}: {lang}")
                                self.lang_combo.set_active_id(lang)
                except Exception as e:
                    print(f"Err Lang: {e}")

                # Zeitzone
                try:
                    res = subprocess.run(
                        ["timedatectl", "show", "-p", "Timezone", "--value"],
                        capture_output=True, text=True
                    )
                    tz = res.stdout.strip()
                    if not self.time_combo.set_active_id(tz):
                        self.time_combo.append(tz, f"{t('Current')}: {tz}")
                        self.time_combo.set_active_id(tz)
                except Exception as e:
                    print(f"Err Time: {e}")
            except Exception as e:
                # Hard backstop: whatever went wrong above (including a
                # bug in this method itself), _load_all() must never let
                # an exception escape — the page falls back to a visible,
                # neutral, still-usable state instead.
                self._set_neutral_state()
                self.show_toast(f"{t('Error:')} {e}")
        finally:
            self.is_loading = False

    # ── Callbacks ─────────────────────────────────────────────────────────

    def show_toast(self, message):
        toast = Adw.Toast.new(message)
        if hasattr(self.main_window, "add_toast"):
            self.main_window.add_toast(toast)

    def _on_layout_changed(self, combo):
        if self.is_loading: return
        lang = combo.get_active_id()
        if not lang: return
        try:
            if load_provider() is Provider.LUA:
                # Write first, then reload — under Lua there is no
                # per-field `hyprctl keyword input:...` (fails outright
                # under the Lua provider).
                _write_input_lua_field("kb_layout", lang)
            else:
                require_config_capability(ConfigCapability.INPUT, writer_provider=Provider.HYPRLANG)
                _write_input_conf_key("kb_layout", lang)
                subprocess.run(["hyprctl", "keyword", "input:kb_layout", lang], check=True)
            self.show_toast(f"Tastaturlayout: {lang.upper()}")
        except Exception as e:
            self.show_toast(f"Fehler: {e}")
            self._revert_input_display()

    def _on_numlock_changed(self, row, _):
        if self.is_loading: return
        val = "true" if row.get_active() else "false"
        try:
            if load_provider() is Provider.LUA:
                _write_input_lua_field("numlock_by_default", row.get_active())
            else:
                require_config_capability(ConfigCapability.INPUT, writer_provider=Provider.HYPRLANG)
                _write_input_conf_key("numlock_by_default", val)
                subprocess.run(["hyprctl", "keyword", "input:numlock_by_default", val], check=True)
            self.show_toast(f"NumLock: {val}")
        except Exception as e:
            self.show_toast(f"Fehler: {e}")
            self._revert_input_display()

    def _on_language_changed(self, combo):
        if self.is_loading: return
        lang = combo.get_active_id()
        if not lang: return
        try:
            subprocess.run(["pkexec", "localectl", "set-locale", f"LANG={lang}"], check=True)
            self.show_toast(t("Language set successfully (reboot needed)."))
        except subprocess.CalledProcessError:
            self.show_toast(t("Language change cancelled."))
            self._load_all()
        except Exception as e:
            self.show_toast(f"Fehler: {e}")
            self._load_all()

    def _on_timezone_changed(self, combo):
        if self.is_loading: return
        tz = combo.get_active_id()
        if not tz: return
        try:
            subprocess.run(["pkexec", "timedatectl", "set-timezone", tz], check=True)
            self.show_toast(t("Timezone set successfully."))
        except subprocess.CalledProcessError:
            self.show_toast(t("Timezone change cancelled."))
            self._load_all()
        except Exception as e:
            self.show_toast(f"Fehler: {e}")
            self._load_all()
