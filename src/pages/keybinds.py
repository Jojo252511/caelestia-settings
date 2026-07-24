import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from src.lang import t
from gi.repository import Gtk, Adw

try:
    import caelestia_core
except ImportError:
    caelestia_core = None

KEYBINDS_CONF = Path.home() / ".config/hypr/hyprland/keybinds.conf"
VARIABLES_CONF = Path.home() / ".config/hypr/variables.conf"

# ── Regex (aus hyprkeys übernommen) ──────────────────────────────────────────

BIND_RE = re.compile(
    r'^(\s*)(bind[a-z]*)\s*=\s*'
    r'([^,]*),\s*'
    r'([^,]*),\s*'
    r'([^,\n#]*?)'
    r'(?:,\s*([^\n#]*?))?'
    r'\s*(?:#\s*(.*))?$',
    re.IGNORECASE,
)
VAR_RE = re.compile(r'^\s*\$([A-Za-z0-9_]+)\s*=\s*(.*)$')

BIND_TYPE_LABELS = {
    "bind":   "Normal",
    "binde":  "Repeat",
    "bindl":  "Lock-Screen",
    "bindle": "Lock+Repeat",
    "bindr":  "Release",
    "bindm":  "Maus",
    "bindi":  "Ignore Inhibit",
    "bindin": "Ignore+NonConsume",
}

DISPATCHERS = sorted([
    "exec", "killactive", "closewindow", "workspace", "movetoworkspace",
    "movetoworkspacesilent", "togglefloating", "fullscreen", "fakefullscreen",
    "dpms", "pin", "movefocus", "movewindow", "resizewindow", "resizeactive",
    "cyclenext", "swapnext", "focuswindow", "focusmonitor", "splitratio",
    "toggleopaque", "movecursortocorner", "workspaceopt", "exit",
    "forcerendererreload", "movecurrentworkspacetomonitor",
    "focusworkspaceoncurrentmonitor", "togglespecialworkspace",
    "swapactiveworkspaces", "bringactivetotop", "alterzorder", "togglesplit",
    "layoutmsg", "global", "submap", "moveoutofgroup", "changegroupactive",
    "togglegroup", "lockactivegroup", "centerwindow",
])


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_variables(path: Path) -> dict:
    if not path.exists():
        return {}
    if caelestia_core is not None:
        try:
            return caelestia_core.parse_variables(path.read_text())
        except Exception as e:
            print(f"Variablen-Parser fehler: {e}")
            return {}
    variables = {}
    try:
        for line in path.read_text().splitlines():
            m = VAR_RE.match(line)
            if m:
                val = re.sub(r'\s*#.*$', '', m.group(2)).strip()
                variables[m.group(1)] = val
        for _ in range(5):
            for k, v in variables.items():
                for rn, rv in variables.items():
                    v = v.replace(f"${rn}", rv)
                variables[k] = v
    except Exception as e:
        print(f"Variablen-Parser fehler: {e}")
    return variables


def _resolve(raw: str, variables: dict) -> str:
    if caelestia_core is not None:
        return caelestia_core.resolve(raw, variables)
    result = raw.strip()
    for name, val in variables.items():
        result = result.replace(f"${name}", val)
    return result


def parse_keybinds() -> list[dict]:
    if not KEYBINDS_CONF.exists():
        return []
    variables = _parse_variables(VARIABLES_CONF)
    binds = []
    try:
        lines = KEYBINDS_CONF.read_text().splitlines()
        for i, line in enumerate(lines):
            m = BIND_RE.match(line)
            if not m:
                continue
            _, btype, mod_raw, key_raw, disp, arg, comment = m.groups()
            mod_raw = mod_raw.strip()
            key_raw = key_raw.strip()
            binds.append({
                "id":                f"bind_{i}",
                "line_number":       i,
                "raw_line":          line,
                "bind_type":         btype.lower(),
                "modifier_raw":      mod_raw,
                "modifier_resolved": _resolve(mod_raw, variables),
                "key_raw":           key_raw,
                "key_resolved":      _resolve(key_raw, variables),
                "dispatcher":        (disp or "").strip(),
                "argument":          (arg or "").strip(),
                "comment":           (comment or "").strip(),
            })
    except Exception as e:
        print(f"Keybinds-Parser fehler: {e}")
    return binds


def _backup():
    if KEYBINDS_CONF.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(KEYBINDS_CONF,
                     KEYBINDS_CONF.with_suffix(f".bak_{ts}.conf"))


def _build_line(data: dict) -> str:
    line = f"{data['bind_type']} = {data['modifier']}, {data['key']}, {data['dispatcher']}"
    if data.get("argument"):
        line += f", {data['argument']}"
    if data.get("comment"):
        line += f"  # {data['comment']}"
    return line


def _find_line(lines: list[str], line_number: int, raw_line: str | None) -> int | None:
    """Returns the actual index for the line, re-searching by content if the file changed."""
    if raw_line is not None:
        if 0 <= line_number < len(lines) and lines[line_number].strip() == raw_line.strip():
            return line_number
        for i, line in enumerate(lines):
            if line.strip() == raw_line.strip():
                return i
        return None
    return line_number if 0 <= line_number < len(lines) else None


def save_keybind(data: dict, line_number: int | None = None, raw_line: str | None = None):
    _backup()
    KEYBINDS_CONF.parent.mkdir(parents=True, exist_ok=True)
    if not KEYBINDS_CONF.exists():
        KEYBINDS_CONF.touch()
    new_line = _build_line(data)
    lines = KEYBINDS_CONF.read_text().splitlines()
    if line_number is not None:
        idx = _find_line(lines, line_number, raw_line)
        if idx is not None:
            lines[idx] = new_line
        else:
            lines.append(new_line)
    else:
        lines.append(new_line)
    KEYBINDS_CONF.write_text("\n".join(lines) + "\n")
    try:
        subprocess.run(["hyprctl", "reload"], capture_output=True, timeout=3)
    except Exception:
        pass


def delete_keybind(line_number: int, raw_line: str | None = None):
    _backup()
    lines = KEYBINDS_CONF.read_text().splitlines()
    idx = _find_line(lines, line_number, raw_line)
    if idx is not None:
        lines.pop(idx)
        KEYBINDS_CONF.write_text("\n".join(lines) + "\n")
    try:
        subprocess.run(["hyprctl", "reload"], capture_output=True, timeout=3)
    except Exception:
        pass


# ── Keybind-Dialog ────────────────────────────────────────────────────────────

class KeybindDialog(Gtk.Dialog):
    """Kompakter Dialog im Grid-Layout — kein zerhacktes ActionRow-Design."""

    def __init__(self, parent, bind: dict | None = None):
        super().__init__(
            title=t("Edit keybind") if bind else t("New keybind"),
            transient_for=parent,
            modal=True,
        )
        self._line_number = bind["line_number"] if bind else None
        self.set_default_size(480, -1)

        self.add_button(t("Cancel"), Gtk.ResponseType.CANCEL)
        save_btn = self.add_button(t("Save"), Gtk.ResponseType.OK)
        save_btn.add_css_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)

        grid = Gtk.Grid()
        grid.set_row_spacing(10)
        grid.set_column_spacing(12)
        grid.set_margin_top(16); grid.set_margin_bottom(16)
        grid.set_margin_start(16); grid.set_margin_end(16)

        def _lbl(text, row):
            lbl = Gtk.Label(label=text)
            lbl.set_halign(Gtk.Align.END)
            lbl.add_css_class("dim-label")
            grid.attach(lbl, 0, row, 1, 1)

        # Bind-Typ
        _lbl(t("Bind type"), 0)
        self._type_combo = Gtk.ComboBoxText()
        self._type_combo.set_hexpand(True)
        for bt, label in BIND_TYPE_LABELS.items():
            self._type_combo.append(bt, f"{bt} — {label}")
        self._type_combo.set_active_id(bind["bind_type"] if bind else "bind")
        grid.attach(self._type_combo, 1, 0, 1, 1)

        # Modifier
        _lbl(t("Modifier"), 1)
        self._mod_entry = Gtk.Entry()
        self._mod_entry.set_hexpand(True)
        self._mod_entry.set_placeholder_text("SUPER, CTRL SHIFT, $mainMod …")
        self._mod_entry.set_text(bind["modifier_raw"] if bind else "SUPER")
        grid.attach(self._mod_entry, 1, 1, 1, 1)

        # Taste
        _lbl("Taste", 2)
        self._key_entry = Gtk.Entry()
        self._key_entry.set_hexpand(True)
        self._key_entry.set_placeholder_text("T, Return, F1, mouse:272 …")
        self._key_entry.set_text(bind["key_raw"] if bind else "")
        grid.attach(self._key_entry, 1, 2, 1, 1)

        # Dispatcher
        _lbl(t("Dispatcher"), 3)
        self._disp_combo = Gtk.ComboBoxText()
        self._disp_combo.set_hexpand(True)
        for d in DISPATCHERS:
            self._disp_combo.append(d, d)
        self._disp_combo.set_active_id(bind["dispatcher"] if bind else "exec")
        grid.attach(self._disp_combo, 1, 3, 1, 1)

        # Argument
        _lbl(t("Argument"), 4)
        self._arg_entry = Gtk.Entry()
        self._arg_entry.set_hexpand(True)
        self._arg_entry.set_placeholder_text("optional — kitty, 1, toggle …")
        self._arg_entry.set_text(bind["argument"] if bind else "")
        grid.attach(self._arg_entry, 1, 4, 1, 1)

        # Kommentar
        _lbl(t("Comment"), 5)
        self._comment_entry = Gtk.Entry()
        self._comment_entry.set_hexpand(True)
        self._comment_entry.set_placeholder_text("optional")
        self._comment_entry.set_text(bind["comment"] if bind else "")
        grid.attach(self._comment_entry, 1, 5, 1, 1)

        self.get_content_area().append(grid)
        self._key_entry.connect("activate", lambda _: self.response(Gtk.ResponseType.OK))
        self._arg_entry.connect("activate", lambda _: self.response(Gtk.ResponseType.OK))

    def get_data(self) -> dict:
        return {
            "bind_type":  self._type_combo.get_active_id() or "bind",
            "modifier":   self._mod_entry.get_text().strip(),
            "key":        self._key_entry.get_text().strip(),
            "dispatcher": self._disp_combo.get_active_id() or "exec",
            "argument":   self._arg_entry.get_text().strip(),
            "comment":    self._comment_entry.get_text().strip(),
        }

    @property
    def line_number(self) -> int | None:
        return self._line_number


# ── Haupt-Seite ───────────────────────────────────────────────────────────────

class KeybindsPage(Gtk.Box):
    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.main_window = main_window
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(0)
        self._all_binds: list[dict] = []

        # ── Toolbar ──────────────────────────────────────────────────────
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_top(12); bar.set_margin_bottom(8)
        bar.set_margin_start(12); bar.set_margin_end(12)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text(t("Search: SUPER, exec, kitty..."))
        self._search.set_hexpand(True)
        self._search.connect("search-changed", lambda _: self._filter())
        bar.append(self._search)

        self._type_filter = Gtk.ComboBoxText()
        self._type_filter.append("", t("All types"))
        for bt in BIND_TYPE_LABELS:
            self._type_filter.append(bt, bt)
        self._type_filter.set_active(0)
        self._type_filter.connect("changed", lambda _: self._filter())
        bar.append(self._type_filter)

        add_btn = Gtk.Button(label=t("+ New"))
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add)
        bar.append(add_btn)

        reload_btn = Gtk.Button()
        reload_btn.set_icon_name("view-refresh-symbolic")
        reload_btn.set_tooltip_text(t("Reload"))
        reload_btn.connect("clicked", lambda _: self._load())
        bar.append(reload_btn)

        self._count_label = Gtk.Label()
        self._count_label.add_css_class("caption")
        self._count_label.add_css_class("dim-label")
        bar.append(self._count_label)
        self.append(bar)

        # Pfad
        path_label = Gtk.Label()
        path_label.set_markup(
            f"<small><tt>{str(KEYBINDS_CONF).replace(str(Path.home()), '~')}</tt></small>"
        )
        path_label.add_css_class("dim-label")
        path_label.set_halign(Gtk.Align.CENTER)
        path_label.set_margin_bottom(6)
        self.append(path_label)

        # ── Liste ─────────────────────────────────────────────────────────
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scroller)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_top(4); self._list_box.set_margin_bottom(12)
        self._list_box.set_margin_start(12); self._list_box.set_margin_end(12)
        scroller.set_child(self._list_box)

        self._empty = Adw.StatusPage()
        self._empty.set_icon_name("preferences-desktop-keyboard-symbolic")
        self._empty.set_title(t("No keybinds found"))
        self._empty.set_description(
            t("Check your keybinds.conf or add a new keybind.")
        )
        self._empty.set_vexpand(True)
        self._empty.set_visible(False)
        self.append(self._empty)

        self._load()

    def _load(self):
        self._all_binds = parse_keybinds()
        self._filter()

    def _filter(self):
        q  = self._search.get_text().lower()
        bt = self._type_filter.get_active_id() or ""

        filtered = [
            b for b in self._all_binds
            if (not q or q in " ".join([
                b["modifier_raw"], b["modifier_resolved"],
                b["key_raw"], b["key_resolved"],
                b["dispatcher"], b["argument"], b["comment"]
            ]).lower())
            and (not bt or b["bind_type"] == bt)
        ]

        while row := self._list_box.get_first_child():
            self._list_box.remove(row)

        if not filtered:
            self._list_box.set_visible(False)
            self._empty.set_visible(True)
            self._count_label.set_text("0 Keybinds")
            return

        self._list_box.set_visible(True)
        self._empty.set_visible(False)
        self._count_label.set_text(
            f"{len(filtered)} Keybind{'s' if len(filtered) != 1 else ''}"
        )

        for bind in filtered:
            self._list_box.append(self._make_row(bind))

    def _make_row(self, bind: dict) -> Adw.ActionRow:
        row = Adw.ActionRow()

        mod = bind["modifier_resolved"] or bind["modifier_raw"]
        key = bind["key_resolved"] or bind["key_raw"]
        row.set_title(f"{mod} + {key}" if mod else key)

        def _esc(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        sub = _esc(bind["dispatcher"])
        if bind["argument"]:  sub += f"  {_esc(bind['argument'])}"
        if bind["comment"]:   sub += f"  # {_esc(bind['comment'])}"
        row.set_subtitle(sub)

        # Bind-Typ Badge
        bt_lbl = Gtk.Label(label=bind["bind_type"])
        bt_lbl.add_css_class("caption"); bt_lbl.add_css_class("dim-label")
        bt_lbl.set_valign(Gtk.Align.CENTER); bt_lbl.set_margin_end(4)
        row.add_suffix(bt_lbl)

        edit_btn = Gtk.Button()
        edit_btn.set_icon_name("document-edit-symbolic")
        edit_btn.set_valign(Gtk.Align.CENTER)
        edit_btn.set_tooltip_text("Bearbeiten")
        edit_btn.connect("clicked", lambda _, b=bind: self._on_edit(b))
        row.add_suffix(edit_btn)

        del_btn = Gtk.Button()
        del_btn.set_icon_name("user-trash-symbolic")
        del_btn.add_css_class("destructive-action")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.set_tooltip_text(t("Delete"))
        del_btn.connect("clicked", lambda _, b=bind: self._on_delete(b))
        row.add_suffix(del_btn)

        return row

    def _on_add(self, _btn):
        dlg = KeybindDialog(self.main_window)
        dlg.connect("response", self._on_dialog_response, dlg, None, None)
        dlg.present()

    def _on_edit(self, bind: dict):
        dlg = KeybindDialog(self.main_window, bind)
        dlg.connect("response", self._on_dialog_response, dlg, bind["line_number"], bind.get("raw_line"))
        dlg.present()

    def _on_dialog_response(self, dlg, response, dialog_obj, line_number, raw_line):
        dlg.destroy()
        if response != Gtk.ResponseType.OK:
            return
        data = dialog_obj.get_data()
        if not data["key"] or not data["dispatcher"]:
            self.main_window.add_toast(
                Adw.Toast.new(t("Key and dispatcher are required."))
            )
            return
        try:
            save_keybind(data, line_number, raw_line)
            self._load()
            self.main_window.add_toast(
                Adw.Toast.new(t("Keybind saved and Hyprland reloaded."))
            )
        except Exception as e:
            self.main_window.add_toast(Adw.Toast.new(f"Fehler: {e}"))

    def _on_delete(self, bind: dict):
        mod = bind["modifier_resolved"] or bind["modifier_raw"]
        key = bind["key_resolved"] or bind["key_raw"]
        dlg = Adw.MessageDialog(
            heading=t("Delete keybind?"),
            body=f"{mod} + {key} → {bind['dispatcher']} {bind['argument']}"
        )
        dlg.set_transient_for(self.main_window)
        dlg.add_response("cancel", t("Cancel"))
        dlg.add_response("delete", t("Delete"))
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_resp(d, r):
            if r == "delete":
                try:
                    delete_keybind(bind["line_number"], bind.get("raw_line"))
                    self._load()
                    self.main_window.add_toast(Adw.Toast.new(t("Keybind deleted.")))
                except Exception as e:
                    self.main_window.add_toast(Adw.Toast.new(f"Fehler: {e}"))

        dlg.connect("response", on_resp)
        dlg.present()