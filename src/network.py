"""Wi-Fi access via libnm (NetworkManager's D-Bus API).

Secrets are handed to NetworkManager over D-Bus, so they never appear in the
argument vector of a helper process where any local user could read them from
`ps` or /proc/<pid>/cmdline.
"""

import gi

gi.require_version("NM", "1.0")

from gi.repository import GLib, NM

from src.lang import t

_AP_SEC = getattr(NM, "80211ApSecurityFlags")
_AP_FLAGS = getattr(NM, "80211ApFlags")

_ENTERPRISE = int(_AP_SEC.KEY_MGMT_802_1X | _AP_SEC.KEY_MGMT_EAP_SUITE_B_192)
_PSK = int(_AP_SEC.KEY_MGMT_PSK)
_SAE = int(_AP_SEC.KEY_MGMT_SAE)
_OWE = int(_AP_SEC.KEY_MGMT_OWE | _AP_SEC.KEY_MGMT_OWE_TM)
_PRIVACY = int(_AP_FLAGS.PRIVACY)

KEY_MGMT_OPEN = ""
KEY_MGMT_WEP = "none"
KEY_MGMT_WPA_PSK = "wpa-psk"
KEY_MGMT_SAE = "sae"
KEY_MGMT_OWE = "owe"

ACTIVATION_TIMEOUT_SECONDS = 45

_client = None


def key_mgmt_for_ap(ap_flags: int, wpa_flags: int, rsn_flags: int) -> str | None:
    """Key management mode for an access point.

    Returns `KEY_MGMT_OPEN` for unsecured networks and `None` for enterprise
    networks, whose credentials the Wi-Fi page does not collect.
    """
    secured = wpa_flags | rsn_flags
    if secured & _ENTERPRISE:
        return None
    # WPA3 transition APs advertise PSK and SAE; "wpa-psk" covers both.
    if secured & _PSK:
        return KEY_MGMT_WPA_PSK
    if secured & _SAE:
        return KEY_MGMT_SAE
    if secured & _OWE:
        return KEY_MGMT_OWE
    if ap_flags & _PRIVACY:
        return KEY_MGMT_WEP
    return KEY_MGMT_OPEN


def build_wifi_connection(ssid: str, key_mgmt: str, password: str | None) -> NM.SimpleConnection:
    """Connection profile for a Wi-Fi network."""
    connection = NM.SimpleConnection.new()

    s_con = NM.SettingConnection.new()
    s_con.set_property(NM.SETTING_CONNECTION_ID, ssid)
    s_con.set_property(NM.SETTING_CONNECTION_UUID, NM.utils_uuid_generate())
    s_con.set_property(NM.SETTING_CONNECTION_TYPE, NM.SETTING_WIRELESS_SETTING_NAME)
    connection.add_setting(s_con)

    s_wifi = NM.SettingWireless.new()
    s_wifi.set_property(NM.SETTING_WIRELESS_SSID, GLib.Bytes.new(ssid.encode("utf-8")))
    connection.add_setting(s_wifi)

    if key_mgmt != KEY_MGMT_OPEN:
        s_sec = NM.SettingWirelessSecurity.new()
        s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_KEY_MGMT, key_mgmt)
        _set_secret(s_sec, key_mgmt, password)
        connection.add_setting(s_sec)

    return connection


def _set_secret(s_sec: NM.SettingWirelessSecurity, key_mgmt: str, password: str | None) -> None:
    if not password:
        return
    if key_mgmt == KEY_MGMT_WEP:
        s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_WEP_KEY0, password)
    elif key_mgmt in (KEY_MGMT_WPA_PSK, KEY_MGMT_SAE):
        s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_PSK, password)


def connect(ssid: str, password: str | None, on_done) -> None:
    """Activate `ssid`, reporting `(success, detail)` to `on_done` when settled.

    Runs asynchronously on the GTK main loop; `on_done` is called from it too.
    """
    client = _get_client()
    if client is None:
        on_done(False, t("NetworkManager is not available."))
        return

    device = _wifi_device(client)
    if device is None:
        on_done(False, t("No Wi-Fi adapter found."))
        return

    ap = _find_access_point(device, ssid)
    if ap is None:
        on_done(False, t("Network not found."))
        return

    key_mgmt = key_mgmt_for_ap(ap.get_flags(), ap.get_wpa_flags(), ap.get_rsn_flags())
    if key_mgmt is None:
        on_done(False, t("Enterprise networks are not supported."))
        return

    saved = _find_saved_connection(client, ssid)
    if saved is None:
        connection = build_wifi_connection(ssid, key_mgmt, password)
        client.add_and_activate_connection_async(
            connection, device, ap.get_path(), None, _on_add_and_activate, on_done
        )
        return

    if password:
        s_sec = saved.get_setting_wireless_security()
        if s_sec is None:
            s_sec = NM.SettingWirelessSecurity.new()
            s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_KEY_MGMT, key_mgmt)
            saved.add_setting(s_sec)
        _set_secret(s_sec, s_sec.get_key_mgmt() or key_mgmt, password)
        saved.commit_changes_async(True, None, _on_commit, (client, saved, device, ap, on_done))
    else:
        _activate(client, saved, device, ap, on_done)


def _get_client():
    global _client
    if _client is None:
        try:
            _client = NM.Client.new(None)
        except GLib.Error:
            return None
    return _client


def _wifi_device(client):
    for device in client.get_devices():
        if device.get_device_type() == NM.DeviceType.WIFI:
            return device
    return None


def _find_access_point(device, ssid: str):
    wanted = ssid.encode("utf-8")
    best = None
    for ap in device.get_access_points():
        raw = ap.get_ssid()
        if raw is None or raw.get_data() != wanted:
            continue
        if best is None or ap.get_strength() > best.get_strength():
            best = ap
    return best


def _find_saved_connection(client, ssid: str):
    wanted = ssid.encode("utf-8")
    for connection in client.get_connections():
        s_wifi = connection.get_setting_wireless()
        if s_wifi is None:
            continue
        # Hotspot profiles can carry the same SSID but must never be joined.
        if s_wifi.get_mode() not in (None, NM.SETTING_WIRELESS_MODE_INFRA):
            continue
        raw = s_wifi.get_ssid()
        if raw is not None and raw.get_data() == wanted:
            return connection
    return None


def _on_commit(saved, result, data):
    client, connection, device, ap, on_done = data
    try:
        saved.commit_changes_finish(result)
    except GLib.Error as err:
        on_done(False, err.message)
        return
    _activate(client, connection, device, ap, on_done)


def _activate(client, connection, device, ap, on_done):
    client.activate_connection_async(connection, device, ap.get_path(), None, _on_activate, on_done)


def _on_activate(client, result, on_done):
    try:
        active = client.activate_connection_finish(result)
    except GLib.Error as err:
        on_done(False, err.message)
        return
    _watch_activation(active, on_done)


def _on_add_and_activate(client, result, on_done):
    try:
        active = client.add_and_activate_connection_finish(result)
    except GLib.Error as err:
        on_done(False, err.message)
        return
    # A profile NetworkManager just created for us is worthless if the
    # activation fails (typically a wrong password), and would otherwise be
    # retried by autoconnect forever.
    _watch_activation(active, on_done, delete_on_failure=True)


def _watch_activation(active, on_done, delete_on_failure=False):
    handler = 0
    timeout = 0
    settled = False

    def finish(success, detail):
        nonlocal settled
        if settled:
            return
        settled = True
        if handler:
            active.disconnect(handler)
        if timeout:
            GLib.source_remove(timeout)
        if not success and delete_on_failure:
            _delete_connection(active.get_connection())
        on_done(success, detail)

    def on_state_changed(_active, state, reason):
        if state == NM.ActiveConnectionState.ACTIVATED:
            finish(True, "")
        elif state == NM.ActiveConnectionState.DEACTIVATED:
            finish(False, _reason_detail(reason))

    def on_timeout():
        finish(False, t("Connection timed out."))
        return False

    handler = active.connect("state-changed", on_state_changed)
    timeout = GLib.timeout_add_seconds(ACTIVATION_TIMEOUT_SECONDS, on_timeout)

    if active.get_state() == NM.ActiveConnectionState.ACTIVATED:
        finish(True, "")


def _delete_connection(connection):
    if connection is not None:
        connection.delete_async(None, _on_delete, None)


def _on_delete(connection, result, _data):
    try:
        connection.delete_finish(result)
    except GLib.Error as err:
        print(f"Wi-Fi: could not remove failed profile: {err.message}")


def _reason_detail(reason) -> str:
    if reason == NM.ActiveConnectionStateReason.NO_SECRETS:
        return t("Incorrect password")
    return NM.ActiveConnectionStateReason(reason).value_nick
