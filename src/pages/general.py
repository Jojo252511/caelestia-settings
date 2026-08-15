import re
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
    write_managed_lua_block_and_reload,
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
# other top-level sections (general, decoration, ...), and other input
# fields this app doesn't own (touchpad, sensitivity, ...). Hyprland itself
# applies whichever static assignment of a field appears LAST in the file,
# so reading mirrors that: every hl.config(...) call is located with
# caelestia_core.find_lua_calls and scanned in file order, and the last
# statically-known value per field wins. A call (or a single field within
# one) that isn't a supported static shape is simply skipped — read-only,
# never rewritten, never a reason to abort reading the rest of the file.
#
# The app's own writes only ever touch a single hl.config({ input = {...} })
# call inside the "input" managed block. When only one of the two fields
# changes, the other field's value is taken from the app's OWN managed
# block (never from some other manual call elsewhere in the file) so a
# partial update never adopts or overwrites content it doesn't own.


def _merge_static_input_calls(text: str) -> dict:
    """Scans `text` for every hl.config({ input = {...} }) call and returns
    the last statically-known value per input field, in file order — later
    static assignments win; dynamic/unsupported values for a field simply
    don't produce an assignment and leave any earlier value in place."""
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
    app's own "input" managed block only (not the whole file) — the safe
    source of truth a partial write must preserve for the field it isn't
    currently changing. Propagates ManagedBlockError if the block's own
    marker structure is corrupted, rather than silently ignoring it."""
    path = resolve_path("input", Provider.LUA)
    lines = read_managed_lua_block(path, INPUT_LUA_BLOCK)
    if not lines:
        return {}
    return _merge_static_input_calls("\n".join(lines))


def _read_input_lua() -> dict:
    """Effective (whole-file, last-static-assignment-wins) input.kb_layout /
    input.numlock_by_default as strings, matching the legacy dict contract
    of read_input_conf(). A field is simply absent when it can't be
    statically determined anywhere in the file — callers must not guess a
    default on its behalf."""
    path = resolve_path("input", Provider.LUA)
    if not path.exists():
        return {}
    text = path.read_bytes().decode("utf-8")
    # Validates marker structure as a side effect (raises ManagedBlockError
    # on a corrupted managed block) — the byte range itself isn't needed
    # since effective values are resolved across the whole file.
    managed_block_byte_range(path, INPUT_LUA_BLOCK)
    fields = _merge_static_input_calls(text)
    result = {}
    if "kb_layout" in fields:
        result["kb_layout"] = fields["kb_layout"]
    if "numlock_by_default" in fields:
        result["numlock_by_default"] = "true" if fields["numlock_by_default"] else "false"
    return result


def _write_input_lua_field(key: str, value) -> None:
    """Sets a single input.* field (kb_layout: str, numlock_by_default:
    bool) in the app's managed hl.config({...}) call inside input.lua,
    preserving whatever value the OTHER field already had in the app's own
    managed block — never a guessed default, never a value adopted from
    some other manual call elsewhere in the file."""
    require_config_capability(ConfigCapability.INPUT, writer_provider=Provider.LUA)
    path = resolve_path("input", Provider.LUA)
    fields = _read_own_managed_input_fields()
    fields[key] = value
    ordered = {}
    if "kb_layout" in fields:
        ordered["kb_layout"] = fields["kb_layout"]
    if "numlock_by_default" in fields:
        ordered["numlock_by_default"] = fields["numlock_by_default"]
    line = caelestia_core.render_lua_call("hl.config", [{"input": ordered}])
    write_managed_lua_block_and_reload(path, INPUT_LUA_BLOCK, [line])


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
        self._load_all(provider)
        return True

    def on_provider_changed(self, provider: Provider | None):
        self.load_if_available(provider)

    def _load_all(self, provider: Provider | None | object = _PROVIDER_UNSET):
        self.is_loading = True

        if provider is _PROVIDER_UNSET:
            provider = load_provider()
        if not capability_available(provider, ConfigCapability.INPUT):
            self._set_neutral_state()
            return

        conf = read_input_conf(provider)

        # Tastaturlayout
        layout = conf.get("kb_layout", "us").lower()
        if not self.layout_combo.set_active_id(layout):
            # Unbekanntes Layout ans Ende anhängen
            self.layout_combo.append(layout, f"Unbekannt  ({layout})")
            self.layout_combo.set_active_id(layout)

        # NumLock
        numlock_val = conf.get("numlock_by_default", "false").lower()
        self.numlock_row.set_active(numlock_val == "true")

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
