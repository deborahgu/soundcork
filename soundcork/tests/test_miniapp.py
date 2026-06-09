from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundcork.miniapp import (
    STARTED_OPTIMISTIC_SECONDS,
    get_miniapp_router,
    use_started_state,
)
from soundcork.model import Preset

ACCOUNT_ID = "8208423"
DEVICE_ID = "device-1"
CONTENT_ITEM_ID = "4"
STARTED_AT = 1000.0
STARTED_AT_QUERY = "1000"


def inside_started_window() -> float:
    return STARTED_AT + STARTED_OPTIMISTIC_SECONDS / 2


def outside_started_window() -> float:
    return STARTED_AT + STARTED_OPTIMISTIC_SECONDS + 1.0


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
        now_playing_status=None,
        online: bool = True,
        in_soundcork: bool = True,
        marge_server: str = "Soundcork",
    ) -> None:
        self.play_result = play_result
        self.now_playing_status = now_playing_status
        self.online = online
        self.in_soundcork = in_soundcork
        self.marge_server = marge_server
        self.play_calls: list[tuple[str, str]] = []
        self.stop_calls: list[str] = []

    def all_devices(self):
        return {
            DEVICE_ID: SimpleNamespace(
                id=DEVICE_ID,
                account=ACCOUNT_ID,
                online=self.online,
                in_soundcork=self.in_soundcork,
                marge_server=self.marge_server,
            )
        }

    def play_content_item(self, device_id: str, content_item_id: str) -> bool:
        self.play_calls.append((device_id, content_item_id))
        return self.play_result

    def stop_playback(self, device_id: str) -> bool:
        self.stop_calls.append(device_id)
        return True

    def get_now_playing_status(self, device_id: str):
        assert device_id == DEVICE_ID
        return self.now_playing_status

    def get_volume(self, device_id: str):
        assert device_id == DEVICE_ID
        return SimpleNamespace(Actual=23, Target=23, IsMuted=False)


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
    assert "ložnice" in response.text
    assert "Rádio Proglas" in response.text


def test_dashboard_ignores_stale_selected_device(monkeypatch):
    client, _speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.get(
        f"/miniapp/dashboard?selected_device_id=stale-device&selected_content_item_id={CONTENT_ITEM_ID}"
    )

    assert response.status_code == 200
    assert "No speaker selected." in response.text
    assert "Selected audio source: Rádio Proglas" in response.text


def test_dashboard_ignores_unknown_selected_content_item(monkeypatch):
    client, _speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.get(
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}&selected_content_item_id=stale-content"
    )

    assert response.status_code == 200
    assert "Selected speaker: ložnice" in response.text
    assert "No preset selected." in response.text


def test_dashboard_ignores_non_actionable_selected_device(monkeypatch):
    speakers = FakeSpeakers(online=False)
    client, _speakers = make_client(monkeypatch, speakers=speakers)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.get(
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}&selected_content_item_id={CONTENT_ITEM_ID}"
    )

    assert response.status_code == 200
    assert "No speaker selected." in response.text
    assert "Selected audio source: Rádio Proglas" in response.text


def test_play_redirect_marks_just_started(monkeypatch):
    monkeypatch.setattr("soundcork.miniapp.time.time", lambda: 1000.1234)
    client, speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        f"/miniapp/play?selected_device_id={DEVICE_ID}&selected_content_item_id={CONTENT_ITEM_ID}",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"/miniapp/dashboard?selected_device_id={DEVICE_ID}&selected_content_item_id={CONTENT_ITEM_ID}&started=true&started_at=1000.123"
    )
    assert speakers.play_calls == [(DEVICE_ID, CONTENT_ITEM_ID)]


def test_play_ignores_stale_selected_device(monkeypatch):
    client, speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        f"/miniapp/play?selected_device_id=stale-device&selected_content_item_id={CONTENT_ITEM_ID}",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"/miniapp/dashboard?selected_content_item_id={CONTENT_ITEM_ID}"
    )
    assert speakers.play_calls == []


def test_play_ignores_unknown_selected_content_item(monkeypatch):
    client, speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        f"/miniapp/play?selected_device_id={DEVICE_ID}&selected_content_item_id=stale-content",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}"
    )
    assert speakers.play_calls == []


def test_select_content_item_plays_when_device_is_selected(monkeypatch):
    monkeypatch.setattr("soundcork.miniapp.time.time", lambda: 1000.1234)
    client, speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        f"/miniapp/select-content-item?selected_device_id={DEVICE_ID}",
        data={"content_item_id": CONTENT_ITEM_ID, "content_item_name": "Radio preset"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"/miniapp/dashboard?selected_content_item_id={CONTENT_ITEM_ID}&selected_device_id={DEVICE_ID}&started=true&started_at=1000.123"
    )
    assert speakers.play_calls == [(DEVICE_ID, CONTENT_ITEM_ID)]


def test_select_content_item_with_stale_device_only_selects(monkeypatch):
    client, speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        "/miniapp/select-content-item?selected_device_id=stale-device",
        data={"content_item_id": CONTENT_ITEM_ID, "content_item_name": "Radio preset"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"/miniapp/dashboard?selected_content_item_id={CONTENT_ITEM_ID}"
    )
    assert speakers.play_calls == []


def test_select_content_item_without_device_only_selects(monkeypatch):
    client, speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        "/miniapp/select-content-item",
        data={"content_item_id": CONTENT_ITEM_ID, "content_item_name": "Radio preset"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"/miniapp/dashboard?selected_content_item_id={CONTENT_ITEM_ID}"
    )
    assert speakers.play_calls == []


def test_select_device_ignores_unknown_selected_content_item(monkeypatch):
    client, speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        "/miniapp/select-device?selected_content_item_id=stale-content",
        data={"device_id": DEVICE_ID, "device_name": "ložnice"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"/miniapp/dashboard?selected_device_id={DEVICE_ID}"
    )
    assert speakers.play_calls == []


def test_stop_ignores_stale_selected_device(monkeypatch):
    client, speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        f"/miniapp/stop?selected_device_id=stale-device&selected_content_item_id={CONTENT_ITEM_ID}",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"/miniapp/dashboard?selected_content_item_id={CONTENT_ITEM_ID}"
    )
    assert speakers.stop_calls == []


def test_started_dashboard_shows_optimistic_playback_state(monkeypatch):
    monkeypatch.setattr("soundcork.miniapp.time.time", inside_started_window)
    client, _speakers = make_client(monkeypatch)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)
    client.cookies.set("soundcork_account_label", "%C3%9A%C4%8Det%20lo%C5%BEnice")

    response = client.get(
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}&selected_content_item_id={CONTENT_ITEM_ID}&started=true&started_at={STARTED_AT_QUERY}"
    )

    assert response.status_code == 200
    assert "Now Playing on ložnice" in response.text
    assert "Rádio Proglas" in response.text
    assert "Volume: 23" in response.text
    assert "Stop" in response.text


def test_started_dashboard_overrides_stale_playing_metadata(monkeypatch):
    monkeypatch.setattr("soundcork.miniapp.time.time", inside_started_window)
    stale_now_playing = SimpleNamespace(
        StationName="CRo D-dur",
        ContentItem=SimpleNamespace(Name="CRo D-dur"),
        ContainerArtUrl="http://example.com/ddur.png",
        PlayStatus="PLAY_STATE",
    )
    speakers = FakeSpeakers(now_playing_status=stale_now_playing)
    client, _speakers = make_client(monkeypatch, speakers=speakers)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)
    client.cookies.set("soundcork_account_label", "%C3%9A%C4%8Det%20lo%C5%BEnice")

    response = client.get(
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}&selected_content_item_id={CONTENT_ITEM_ID}&started=true&started_at={STARTED_AT_QUERY}"
    )

    assert response.status_code == 200
    assert "Now Playing on ložnice" in response.text
    assert "Rádio Proglas" in response.text
    assert "CRo D-dur" not in response.text
    assert "Stop" in response.text


def test_started_dashboard_uses_actual_metadata_after_optimistic_window(monkeypatch):
    monkeypatch.setattr("soundcork.miniapp.time.time", outside_started_window)
    stale_now_playing = SimpleNamespace(
        StationName="CRo D-dur",
        ContentItem=SimpleNamespace(Name="CRo D-dur"),
        ContainerArtUrl="http://example.com/ddur.png",
        PlayStatus="PLAY_STATE",
    )
    speakers = FakeSpeakers(now_playing_status=stale_now_playing)
    client, _speakers = make_client(monkeypatch, speakers=speakers)
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.get(
        f"/miniapp/dashboard?selected_device_id={DEVICE_ID}&selected_content_item_id={CONTENT_ITEM_ID}&started=true&started_at={STARTED_AT_QUERY}"
    )

    assert response.status_code == 200
    assert "CRo D-dur" in response.text


def test_use_started_state_is_short_lived(monkeypatch):
    monkeypatch.setattr("soundcork.miniapp.time.time", inside_started_window)

    assert use_started_state(True, STARTED_AT)
    assert not use_started_state(True, STARTED_AT - STARTED_OPTIMISTIC_SECONDS)
    assert not use_started_state(True, None)
    assert not use_started_state(False, STARTED_AT)


def test_started_optimistic_window_is_three_seconds():
    assert STARTED_OPTIMISTIC_SECONDS == 3.0
