"""Tests for the SpeakerAllowlist class."""

from unittest.mock import MagicMock

from soundcork.model import DeviceInfo
from soundcork.speaker_allowlist import SpeakerAllowlist


def _make_device_info(ip: str, device_id: str = "AABBCCDDEEFF") -> DeviceInfo:
    return DeviceInfo(
        device_id=device_id,
        product_code="SoundTouch 20",
        device_serial_number="SN123",
        product_serial_number="PSN123",
        firmware_version="27.0",
        ip_address=ip,
        name="Test Speaker",
    )


class TestSpeakerAllowlist:
    def test_allows_registered_speaker_ip(self):
        ds = MagicMock()
        ds.list_accounts.return_value = ["12345"]
        ds.list_devices.return_value = ["AABBCCDDEEFF"]
        ds.get_device_info.return_value = _make_device_info("192.168.1.143")

        allowlist = SpeakerAllowlist(ds)

        assert allowlist.is_allowed("192.168.1.143") is True

    def test_blocks_public_ip(self):
        ds = MagicMock()
        ds.list_accounts.return_value = ["12345"]
        ds.list_devices.return_value = ["AABBCCDDEEFF"]
        ds.get_device_info.return_value = _make_device_info("192.168.1.143")

        allowlist = SpeakerAllowlist(ds)

        assert allowlist.is_allowed("8.8.8.8") is False

    def test_allows_private_ip(self):
        """Private RFC1918 IPs are allowed (speakers behind NAT)."""
        ds = MagicMock()
        ds.list_accounts.return_value = []

        allowlist = SpeakerAllowlist(ds)

        assert allowlist.is_allowed("192.168.1.200") is True
        assert allowlist.is_allowed("10.0.0.99") is True
        assert allowlist.is_allowed("172.16.5.1") is True

    def test_allows_loopback(self):
        ds = MagicMock()
        ds.list_accounts.return_value = []

        allowlist = SpeakerAllowlist(ds)

        assert allowlist.is_allowed("127.0.0.1") is True
        assert allowlist.is_allowed("::1") is True

    def test_multiple_accounts_and_devices(self):
        ds = MagicMock()
        ds.list_accounts.return_value = ["111", "222"]
        ds.list_devices.side_effect = [
            ["AAAA00000001"],
            ["BBBB00000002", "CCCC00000003"],
        ]
        ds.get_device_info.side_effect = [
            _make_device_info("192.168.1.10", "AAAA00000001"),
            _make_device_info("192.168.1.20", "BBBB00000002"),
            _make_device_info("192.168.1.30", "CCCC00000003"),
        ]

        allowlist = SpeakerAllowlist(ds)

        assert allowlist.is_allowed("192.168.1.10") is True
        assert allowlist.is_allowed("192.168.1.20") is True
        assert allowlist.is_allowed("192.168.1.30") is True
        assert allowlist.is_allowed("8.8.4.4") is False

    def test_refresh_picks_up_new_speakers(self):
        ds = MagicMock()
        # Initially empty
        ds.list_accounts.return_value = []
        allowlist = SpeakerAllowlist(ds)
        assert allowlist.is_registered_speaker("192.168.1.50") is False

        # After adding a device
        ds.list_accounts.return_value = ["999"]
        ds.list_devices.return_value = ["DDDD00000004"]
        ds.get_device_info.return_value = _make_device_info("192.168.1.50")

        allowlist.refresh()

        assert allowlist.is_registered_speaker("192.168.1.50") is True

    def test_handles_datastore_errors_gracefully(self):
        ds = MagicMock()
        ds.list_accounts.side_effect = Exception("disk error")

        # Should not crash, just have an empty allowlist (+ loopback)
        allowlist = SpeakerAllowlist(ds)

        assert allowlist.is_allowed("127.0.0.1") is True
        assert allowlist.is_allowed("8.8.8.8") is False

    def test_handles_device_info_error_gracefully(self):
        ds = MagicMock()
        ds.list_accounts.return_value = ["12345"]
        ds.list_devices.return_value = ["AAAA00000001", "BBBB00000002"]
        ds.get_device_info.side_effect = [
            _make_device_info("192.168.1.10"),
            Exception("corrupt XML"),
        ]

        allowlist = SpeakerAllowlist(ds)

        # First device should still be allowed despite second failing
        assert allowlist.is_allowed("192.168.1.10") is True

    def test_get_allowed_ips_returns_copy(self):
        ds = MagicMock()
        ds.list_accounts.return_value = ["12345"]
        ds.list_devices.return_value = ["AABBCCDDEEFF"]
        ds.get_device_info.return_value = _make_device_info("192.168.1.143")

        allowlist = SpeakerAllowlist(ds)
        ips = allowlist.get_allowed_ips()

        assert "192.168.1.143" in ips
        # Modifying returned set shouldn't affect internal state
        ips.add("8.8.8.8")
        assert "8.8.8.8" not in allowlist.get_allowed_ips()
