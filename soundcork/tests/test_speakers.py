import errno
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from soundcork.config import Settings
from soundcork.ui.speakers import Speakers


class FakeDiscovery:
    def __init__(self, error: OSError) -> None:
        self.error = error
        self.VerifiedDevices: dict[str, object] = {}
        self.calls: list[int] = []

    def DiscoverDevices(self, timeout: int) -> None:
        self.calls.append(timeout)
        raise self.error


def test_initial_discovery_enodev_keeps_configured_devices_available(
    monkeypatch, caplog
):
    discovery = FakeDiscovery(OSError(errno.ENODEV, "No such device"))
    monkeypatch.setattr(
        "soundcork.ui.speakers.SoundTouchDiscovery", lambda **_kwargs: discovery
    )
    datastore = MagicMock()
    datastore.list_accounts.return_value = ["account-id"]
    datastore.list_devices.return_value = ["device-id"]
    datastore.get_device_info.return_value = SimpleNamespace(
        ip_address="192.0.2.20", name="Configured speaker"
    )

    with caplog.at_level(logging.WARNING):
        devices = Speakers(datastore, Settings()).all_devices()

    assert discovery.calls == [1]
    assert "disappearing network interface" in caplog.text
    configured = devices["device-id"]
    assert configured.name == "Configured speaker"
    assert configured.online is False
    assert configured.in_soundcork is True
    assert configured.st_device is None


def test_initial_discovery_propagates_other_os_errors(monkeypatch):
    discovery = FakeDiscovery(OSError(errno.EACCES, "Permission denied"))
    monkeypatch.setattr(
        "soundcork.ui.speakers.SoundTouchDiscovery", lambda **_kwargs: discovery
    )

    with pytest.raises(OSError, match="Permission denied"):
        Speakers(object(), object())
