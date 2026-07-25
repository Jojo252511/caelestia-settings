import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src import network
except (ImportError, ValueError) as err:  # missing PyGObject or the NM typelib
    network = None
    _import_error = err

requires_libnm = unittest.skipIf(network is None, "libnm (NM-1.0 typelib) not available")

# NM_802_11_AP_SEC_* / NM_802_11_AP_FLAGS_*, spelled out so the expectations
# stay readable and independent of the enum lookup in src/network.py.
PRIVACY = 0x1
PAIR_CCMP = 0x8
GROUP_CCMP = 0x80
KEY_MGMT_PSK = 0x100
KEY_MGMT_802_1X = 0x200
KEY_MGMT_SAE = 0x400
KEY_MGMT_OWE = 0x800
KEY_MGMT_EAP_SUITE_B_192 = 0x2000

WPA2_PSK = PAIR_CCMP | GROUP_CCMP | KEY_MGMT_PSK


@requires_libnm
class KeyMgmtForApTest(unittest.TestCase):
    def test_open_network(self):
        self.assertEqual(network.key_mgmt_for_ap(0, 0, 0), network.KEY_MGMT_OPEN)

    def test_wep_is_privacy_without_wpa_or_rsn(self):
        self.assertEqual(network.key_mgmt_for_ap(PRIVACY, 0, 0), network.KEY_MGMT_WEP)

    def test_wpa2_psk(self):
        self.assertEqual(network.key_mgmt_for_ap(PRIVACY, 0, WPA2_PSK), network.KEY_MGMT_WPA_PSK)

    def test_wpa1_only_psk(self):
        self.assertEqual(network.key_mgmt_for_ap(PRIVACY, WPA2_PSK, 0), network.KEY_MGMT_WPA_PSK)

    def test_wpa3_only_is_sae(self):
        rsn = PAIR_CCMP | GROUP_CCMP | KEY_MGMT_SAE
        self.assertEqual(network.key_mgmt_for_ap(PRIVACY, 0, rsn), network.KEY_MGMT_SAE)

    def test_wpa2_wpa3_transition_prefers_psk(self):
        # "wpa-psk" covers WPA2 and WPA3 personal, so it is the safer pick for
        # transition-mode APs that advertise both.
        rsn = PAIR_CCMP | GROUP_CCMP | KEY_MGMT_PSK | KEY_MGMT_SAE
        self.assertEqual(network.key_mgmt_for_ap(PRIVACY, 0, rsn), network.KEY_MGMT_WPA_PSK)

    def test_owe(self):
        self.assertEqual(network.key_mgmt_for_ap(0, 0, KEY_MGMT_OWE), network.KEY_MGMT_OWE)

    def test_enterprise_is_unsupported(self):
        self.assertIsNone(network.key_mgmt_for_ap(PRIVACY, 0, KEY_MGMT_802_1X))
        self.assertIsNone(network.key_mgmt_for_ap(PRIVACY, 0, KEY_MGMT_EAP_SUITE_B_192))

    def test_enterprise_wins_over_psk(self):
        rsn = KEY_MGMT_PSK | KEY_MGMT_802_1X
        self.assertIsNone(network.key_mgmt_for_ap(PRIVACY, 0, rsn))


@requires_libnm
class BuildWifiConnectionTest(unittest.TestCase):
    def test_wpa_psk_profile_is_complete(self):
        conn = network.build_wifi_connection("MyNet", network.KEY_MGMT_WPA_PSK, "hunter2hunter2")
        self.assertTrue(conn.verify())
        self.assertEqual(conn.get_setting_wireless().get_ssid().get_data(), b"MyNet")
        s_sec = conn.get_setting_wireless_security()
        self.assertEqual(s_sec.get_key_mgmt(), "wpa-psk")
        self.assertEqual(s_sec.get_psk(), "hunter2hunter2")

    def test_ssid_is_encoded_as_utf8_bytes(self):
        conn = network.build_wifi_connection("Café-Ätherisch", network.KEY_MGMT_OPEN, None)
        self.assertEqual(
            conn.get_setting_wireless().get_ssid().get_data(),
            "Café-Ätherisch".encode("utf-8"),
        )

    def test_open_network_has_no_security_setting(self):
        conn = network.build_wifi_connection("OpenNet", network.KEY_MGMT_OPEN, None)
        self.assertTrue(conn.verify())
        self.assertIsNone(conn.get_setting_wireless_security())

    def test_wep_uses_wep_key_not_psk(self):
        conn = network.build_wifi_connection("OldNet", network.KEY_MGMT_WEP, "abcde")
        s_sec = conn.get_setting_wireless_security()
        self.assertEqual(s_sec.get_wep_key(0), "abcde")
        self.assertIsNone(s_sec.get_psk())

    def test_sae_uses_psk(self):
        conn = network.build_wifi_connection("Wpa3Net", network.KEY_MGMT_SAE, "hunter2hunter2")
        self.assertEqual(conn.get_setting_wireless_security().get_psk(), "hunter2hunter2")

    def test_owe_takes_no_secret(self):
        conn = network.build_wifi_connection("OweNet", network.KEY_MGMT_OWE, "ignored-password")
        s_sec = conn.get_setting_wireless_security()
        self.assertIsNone(s_sec.get_psk())
        self.assertIsNone(s_sec.get_wep_key(0))

    def test_each_profile_gets_its_own_uuid(self):
        first = network.build_wifi_connection("MyNet", network.KEY_MGMT_OPEN, None)
        second = network.build_wifi_connection("MyNet", network.KEY_MGMT_OPEN, None)
        self.assertNotEqual(first.get_uuid(), second.get_uuid())


class NoPasswordOnCommandLineTest(unittest.TestCase):
    """Regression guard for issue #44."""

    def test_wifi_page_never_passes_a_password_to_nmcli(self):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(os.path.dirname(here), "src", "pages", "wifi.py")) as handle:
            source = handle.read()

        offenders = [
            line.strip()
            for line in source.splitlines()
            if "nmcli" in line and "password" in line.lower()
        ]
        self.assertEqual(offenders, [], "a secret must never reach an nmcli command line")


if __name__ == "__main__":
    unittest.main()
