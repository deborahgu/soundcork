from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundcork.miniapp import get_miniapp_router
from soundcork.model import Preset
from soundcork.ui.speakers import PlaybackState

ACCOUNT_ID = "8208423"
DEVICE_ID = "device-1"


class FakeDatastore:
    def account_exists(self, account_id: str) -> bool:
        return account_id == ACCOUNT_ID

    def list_accounts(self) -> list[str]:
        return [ACCOUNT_ID]

    def get_account_info(self, account_id: str) -> str:
        assert account_id == ACCOUNT_ID
        return "Účet ložnice"

    def list_devices(self, account_id: str) -> list[str]:
        assert account_id == ACCOUNT_ID
        return [DEVICE_ID]

    def get_device_info(self, account_id: str, device_id: str):
        assert account_id == ACCOUNT_ID
        assert device_id == DEVICE_ID
        return SimpleNamespace(
            name="ložnice",
            product_code="SoundTouch10",
            device_id=DEVICE_ID,
        )

    def get_presets(self, account_id: str) -> list[Preset]:
        assert account_id == ACCOUNT_ID
        return [
            Preset(
                id="4",
                name="Rádio Proglas",
                source="LOCAL_INTERNET_RADIO",
                type="STORED_MUSIC",
                location="proglas",
                container_art="",
            )
        ]


class FakeSpeakers:
    def __init__(
        self,
        play_result: bool = True,
        playback_state: PlaybackState | None = None,
        online: bool = True,
        marge_server: str = "Soundcork",
    ) -> None:
        self.play_result = play_result
        self.playback_state = playback_state
        self.online = online
        self.marge_server = marge_server
        self.play_calls: list[tuple[str, str]] = []
        self.playback_calls: list[str] = []

    def all_devices(self):
        return {
            DEVICE_ID: SimpleNamespace(
                account=ACCOUNT_ID,
                online=self.online,
                in_soundcork=True,
                marge_server=self.marge_server,
            )
        }

    def play_content_item(self, device_id: str, content_item_id: str) -> bool:
        self.play_calls.append((device_id, content_item_id))
        return self.play_result

    def get_playback_state(self, device_id: str):
        assert device_id == DEVICE_ID
        self.playback_calls.append(device_id)
        return self.playback_state


def make_client(monkeypatch, speakers: FakeSpeakers | None = None):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    app = FastAPI()
    fake_speakers = speakers or FakeSpeakers()
    app.include_router(
        get_miniapp_router(cast(Any, FakeDatastore()), cast(Any, fake_speakers))
    )
    return TestClient(app), fake_speakers


def set_cookie_headers(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def test_dashboard_decodes_display_cookies(monkeypatch):
    client, _speakers = make_client(monkeypatch)

    response = client.get(
        "/miniapp/dashboard",
        headers={
            "Cookie": (
                f"soundcork_account_id={ACCOUNT_ID}; "
                "soundcork_account_label=%C3%9A%C4%8Det%20lo%C5%BEnice; "
            )
        },
    )

    assert response.status_code == 200
    assert "Účet ložnice" in response.text


def configured_playback_state(soundcork_managed: bool = True) -> PlaybackState:
    now_playing = SimpleNamespace(
        StationName="Rádio Dechovka",
        ContentItem=SimpleNamespace(Name="Rádio Dechovka"),
        ContainerArtUrl="",
        PlayStatus="PLAY_STATE",
    )
    volume = SimpleNamespace(Actual=23, Target=23, IsMuted=False)
    return PlaybackState(
        now_playing=now_playing,
        volume=volume,
        soundcork_managed=soundcork_managed,
    )


def test_dashboard_resolves_selected_configured_device(monkeypatch):
    speakers = FakeSpeakers(
        playback_state=configured_playback_state(),
        online=False,
        marge_server="Unknown",
    )
    client, _speakers = make_client(monkeypatch, speakers=speakers)

    response = client.get(
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}",
        headers={"Cookie": f"soundcork_account_id={ACCOUNT_ID}"},
    )

    assert response.status_code == 200
    assert speakers.playback_calls == [DEVICE_ID]
    assert "Now Playing on ložnice" in response.text
    assert "Rádio Dechovka" in response.text
    assert 'class="device-card online"' in response.text


def test_dashboard_does_not_probe_unselected_configured_device(monkeypatch):
    speakers = FakeSpeakers(online=False, marge_server="Unknown")
    client, _speakers = make_client(monkeypatch, speakers=speakers)

    response = client.get(
        "/miniapp/dashboard",
        headers={"Cookie": f"soundcork_account_id={ACCOUNT_ID}"},
    )

    assert response.status_code == 200
    assert speakers.playback_calls == []
    assert 'class="device-card offline"' in response.text


def test_dashboard_keeps_failed_selected_fallback_offline(monkeypatch):
    speakers = FakeSpeakers(online=False, marge_server="Unknown")
    client, _speakers = make_client(monkeypatch, speakers=speakers)

    response = client.get(
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}",
        headers={"Cookie": f"soundcork_account_id={ACCOUNT_ID}"},
    )

    assert response.status_code == 200
    assert speakers.playback_calls == [DEVICE_ID]
    assert "ložnice" in response.text
    assert 'class="device-card offline"' in response.text


def test_dashboard_keeps_non_soundcork_device_offline(monkeypatch):
    speakers = FakeSpeakers(
        playback_state=configured_playback_state(soundcork_managed=False),
        online=False,
        marge_server="Unknown",
    )
    client, _speakers = make_client(monkeypatch, speakers=speakers)

    response = client.get(
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}",
        headers={"Cookie": f"soundcork_account_id={ACCOUNT_ID}"},
    )

    assert response.status_code == 200
    assert speakers.playback_calls == [DEVICE_ID]
    assert "Rádio Dechovka" in response.text
    assert 'class="device-card offline"' in response.text


def test_dashboard_keeps_discovered_bose_device_offline(monkeypatch):
    speakers = FakeSpeakers(
        playback_state=configured_playback_state(soundcork_managed=False),
        online=True,
        marge_server="Bose",
    )
    client, _speakers = make_client(monkeypatch, speakers=speakers)

    response = client.get(
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}",
        headers={"Cookie": f"soundcork_account_id={ACCOUNT_ID}"},
    )

    assert response.status_code == 200
    assert speakers.playback_calls == [DEVICE_ID]
    assert 'class="device-card offline"' in response.text
