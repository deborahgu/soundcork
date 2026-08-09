import errno
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bosesoundtouchapi.soundtouchclient import SoundTouchDevice  # type: ignore

from soundcork.config import Settings
from soundcork.ui.speakers import PlaybackState, Speakers

DEVICE_ID = "AABBCCDDEEFF"
OTHER_DEVICE_ID = "001122334455"


class FakeDiscovery:
    def __init__(self, error: OSError | None = None) -> None:
        self.error = error
        self.VerifiedDevices: dict[str, object] = {}
        self.calls: list[int] = []

    def DiscoverDevices(self, timeout: int) -> None:
        self.calls.append(timeout)
        if self.error:
            raise self.error


def configured_datastore(device_id: str = DEVICE_ID, ip_address: str = "192.0.2.20"):
    datastore = MagicMock()
    datastore.list_accounts.return_value = ["account-id"]
    datastore.list_devices.return_value = [device_id]
    datastore.get_device_info.return_value = SimpleNamespace(
        ip_address=ip_address, name="Configured speaker"
    )
    return datastore


def configured_soundtouch_device(
    device_id: str = DEVICE_ID, streaming_url: str | None = None
):
    return SimpleNamespace(
        DeviceId=device_id,
        Host="192.0.2.20",
        DeviceName="Configured speaker",
        StreamingAccountUUID="account-id",
        StreamingUrl=streaming_url or f"{Settings().base_url}/marge",
    )


def make_speakers(monkeypatch, datastore=None, discovery=None):
    discovery = discovery or FakeDiscovery()
    monkeypatch.setattr(
        "soundcork.ui.speakers.SoundTouchDiscovery", lambda **_kwargs: discovery
    )
    return Speakers(datastore or configured_datastore(), Settings()), discovery


def install_successful_client(
    monkeypatch, st_device=None, now_playing=None, volume=None
):
    st_device = st_device or configured_soundtouch_device()
    device_constructor = MagicMock(return_value=st_device)
    client = MagicMock()
    client.GetNowPlayingStatus.return_value = now_playing or object()
    client.GetVolume.return_value = volume or SimpleNamespace(
        Actual=23, Target=23, IsMuted=False
    )
    client_constructor = MagicMock(return_value=client)
    monkeypatch.setattr("soundcork.ui.speakers.SoundTouchDevice", device_constructor)
    monkeypatch.setattr("soundcork.ui.speakers.SoundTouchClient", client_constructor)
    return st_device, device_constructor, client, client_constructor


def test_initial_discovery_enodev_keeps_configured_devices_available(
    monkeypatch, caplog
):
    discovery = FakeDiscovery(OSError(errno.ENODEV, "No such device"))
    datastore = configured_datastore(device_id="device-id")

    with caplog.at_level(logging.WARNING):
        speakers, _discovery = make_speakers(
            monkeypatch, datastore=datastore, discovery=discovery
        )
        devices = speakers.all_devices()

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


def test_control_resolves_configured_device_by_ip_without_caching_it(monkeypatch):
    speakers, _discovery = make_speakers(monkeypatch)
    st_device, device_constructor, client, client_constructor = (
        install_successful_client(monkeypatch)
    )

    state = speakers.get_playback_state(DEVICE_ID)

    assert state == PlaybackState(
        now_playing=client.GetNowPlayingStatus.return_value,
        volume=client.GetVolume.return_value,
        soundcork_managed=True,
    )
    call = device_constructor.call_args
    manager = call.kwargs["proxyManager"]
    assert call.kwargs["host"] == "192.0.2.20"
    assert call.kwargs["connectTimeout"] == 1
    client_constructor.assert_called_once_with(st_device, manager=manager)
    timeout = manager.connection_pool_kw["timeout"]
    retries = manager.connection_pool_kw["retries"]
    assert timeout.connect_timeout == 1.0
    assert timeout.read_timeout == 2.0
    assert retries.total == 0

    configured = speakers.all_devices()[DEVICE_ID]
    assert configured.online is False
    assert configured.st_device is None


def test_control_keeps_discovered_device_behavior(monkeypatch):
    st_device = MagicMock(spec=SoundTouchDevice)
    st_device.DeviceId = DEVICE_ID
    st_device.Host = "192.0.2.20"
    st_device.DeviceName = "Discovered speaker"
    st_device.StreamingAccountUUID = "account-id"
    st_device.StreamingUrl = f"{Settings().base_url}/marge"
    discovery = FakeDiscovery()
    discovery.VerifiedDevices = {"192.0.2.20:8090": st_device}
    datastore = MagicMock()
    datastore.list_accounts.return_value = []
    speakers, _discovery = make_speakers(
        monkeypatch, datastore=datastore, discovery=discovery
    )
    fallback_constructor = MagicMock()
    monkeypatch.setattr("soundcork.ui.speakers.SoundTouchDevice", fallback_constructor)
    client = MagicMock()
    monkeypatch.setattr(
        "soundcork.ui.speakers.SoundTouchClient", MagicMock(return_value=client)
    )

    assert speakers.get_playback_state(DEVICE_ID) is not None
    fallback_constructor.assert_not_called()


def test_control_rejects_configured_ip_for_a_different_device(monkeypatch, caplog):
    speakers, _discovery = make_speakers(monkeypatch)
    wrong_device = configured_soundtouch_device(OTHER_DEVICE_ID)
    client_constructor = MagicMock()
    monkeypatch.setattr(
        "soundcork.ui.speakers.SoundTouchDevice", MagicMock(return_value=wrong_device)
    )
    monkeypatch.setattr("soundcork.ui.speakers.SoundTouchClient", client_constructor)

    with caplog.at_level(logging.WARNING):
        assert speakers.get_playback_state(DEVICE_ID) is None

    assert f"belongs to device {OTHER_DEVICE_ID}" in caplog.text
    client_constructor.assert_not_called()
    assert speakers.all_devices()[DEVICE_ID].online is False


def test_control_keeps_unreachable_configured_device_offline(monkeypatch, caplog):
    speakers, _discovery = make_speakers(monkeypatch)
    client_constructor = MagicMock()
    monkeypatch.setattr(
        "soundcork.ui.speakers.SoundTouchDevice",
        MagicMock(side_effect=TimeoutError("speaker did not answer")),
    )
    monkeypatch.setattr("soundcork.ui.speakers.SoundTouchClient", client_constructor)

    with caplog.at_level(logging.INFO):
        assert speakers.get_playback_state(DEVICE_ID) is None

    assert "is not reachable through REST" in caplog.text
    client_constructor.assert_not_called()
    assert speakers.all_devices()[DEVICE_ID].online is False


@pytest.mark.parametrize(
    ("device_id", "configured_ip"),
    [
        ("not-a-device-id", "192.0.2.20"),
        (DEVICE_ID, "not-an-ip"),
        (DEVICE_ID, "127.0.0.1"),
        (DEVICE_ID, "0.0.0.0"),
        (DEVICE_ID, "224.0.0.1"),
        (DEVICE_ID, "169.254.169.254"),
        (DEVICE_ID, "240.0.0.1"),
        (DEVICE_ID, "255.255.255.255"),
        (DEVICE_ID, "2001:db8::20"),
    ],
)
def test_control_rejects_invalid_identity_or_address(
    monkeypatch, device_id, configured_ip
):
    datastore = configured_datastore(device_id=device_id, ip_address=configured_ip)
    speakers, _discovery = make_speakers(monkeypatch, datastore=datastore)
    constructor = MagicMock()
    monkeypatch.setattr("soundcork.ui.speakers.SoundTouchDevice", constructor)

    assert speakers.get_playback_state(device_id) is None
    constructor.assert_not_called()


def test_control_does_not_probe_unknown_configured_device(monkeypatch):
    datastore = MagicMock()
    datastore.list_accounts.return_value = []
    speakers, _discovery = make_speakers(monkeypatch, datastore=datastore)
    constructor = MagicMock()
    monkeypatch.setattr("soundcork.ui.speakers.SoundTouchDevice", constructor)

    assert speakers.get_playback_state(DEVICE_ID) is None
    constructor.assert_not_called()


def test_control_discards_resolution_when_configured_ip_changes(monkeypatch):
    datastore = configured_datastore()
    addresses = iter(["192.0.2.20", "192.0.2.21"])
    datastore.get_device_info.side_effect = lambda *_args: SimpleNamespace(
        ip_address=next(addresses), name="Configured speaker"
    )
    speakers, _discovery = make_speakers(monkeypatch, datastore=datastore)
    st_device, device_constructor, _client, client_constructor = (
        install_successful_client(monkeypatch)
    )

    assert speakers.get_playback_state(DEVICE_ID) is None
    assert device_constructor.call_count == 1
    client_constructor.assert_not_called()


@pytest.mark.parametrize("operation", ["play", "stop"])
def test_mutation_timeout_is_not_retried(monkeypatch, caplog, operation):
    datastore = configured_datastore()
    datastore.get_content_item.return_value = SimpleNamespace(
        name="Rádio Dechovka",
        source="LOCAL_INTERNET_RADIO",
        type="stationurl",
        location="http://example.com/dechovka.mp3",
        source_account="",
        is_presetable=True,
    )
    speakers, _discovery = make_speakers(monkeypatch, datastore=datastore)
    _st_device, device_constructor, client, _client_constructor = (
        install_successful_client(monkeypatch)
    )
    mutation = client.PlayContentItem if operation == "play" else client.MediaStop
    mutation.side_effect = TimeoutError("response was lost")

    with caplog.at_level(logging.ERROR):
        if operation == "play":
            result = speakers.play_content_item(DEVICE_ID, "5")
        else:
            result = speakers.stop_playback(DEVICE_ID)

    assert result is False
    mutation.assert_called_once()
    assert device_constructor.call_count == 1
    assert "outcome may be uncertain" in caplog.text


def test_control_closes_request_local_http_manager(monkeypatch):
    speakers, _discovery = make_speakers(monkeypatch)
    install_successful_client(monkeypatch)
    http_manager = MagicMock()
    monkeypatch.setattr(speakers, "_http_manager", lambda: http_manager)

    assert speakers.get_playback_state(DEVICE_ID) is not None
    http_manager.clear.assert_called_once_with()
