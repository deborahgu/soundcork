from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundcork.miniapp import get_miniapp_router
from soundcork.model import Preset

ACCOUNT_ID = "8208423"
DEVICE_ID = "device-1"


class FakeDatastore:
    def __init__(self, content_source: str = "LOCAL_INTERNET_RADIO") -> None:
        self.content_source = content_source

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

    def get_content_item(self, account: str, device_id: str, ci_id: str):
        assert account == ACCOUNT_ID
        assert device_id == DEVICE_ID
        return SimpleNamespace(source=self.content_source)

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
    def __init__(self, play_result: bool = True) -> None:
        self.play_result = play_result
        self.play_calls: list[tuple[str, str]] = []

    def all_devices(self):
        return {
            DEVICE_ID: SimpleNamespace(
                account=ACCOUNT_ID,
                online=True,
                in_soundcork=True,
                marge_server="Soundcork",
            )
        }

    def play_content_item(self, device_id: str, content_item_id: str) -> bool:
        self.play_calls.append((device_id, content_item_id))
        return self.play_result


class FakePrimer:
    enabled = True

    def __init__(self) -> None:
        self.prime_calls: list[tuple[str, str | None, bool, float]] = []

    def prime_before_play(
        self,
        device_id: str,
        account_id: str | None = None,
        force: bool = True,
        wait_seconds: float = 1.0,
    ) -> bool:
        self.prime_calls.append((device_id, account_id, force, wait_seconds))
        return False


def make_client(
    monkeypatch,
    speakers: FakeSpeakers | None = None,
    datastore: FakeDatastore | None = None,
    primer: FakePrimer | None = None,
):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    app = FastAPI()
    fake_speakers = speakers or FakeSpeakers()
    fake_datastore = datastore or FakeDatastore()
    app.include_router(
        get_miniapp_router(
            cast(Any, fake_datastore), cast(Any, fake_speakers), cast(Any, primer)
        )
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


def test_play_primes_spotify_before_playback_when_primer_configured(monkeypatch):
    primer = FakePrimer()
    client, speakers = make_client(
        monkeypatch,
        datastore=FakeDatastore("SPOTIFY"),
        primer=primer,
    )
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        "/miniapp/play?selected_device_id=device-1&selected_content_item_id=content-1",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "selected_device_id=device-1" in response.headers["location"]
    assert "selected_content_item_id=content-1" in response.headers["location"]
    assert primer.prime_calls == [(DEVICE_ID, ACCOUNT_ID, True, 1.0)]
    assert speakers.play_calls == [(DEVICE_ID, "content-1")]


def test_play_does_not_prime_non_spotify_content(monkeypatch):
    primer = FakePrimer()
    client, speakers = make_client(
        monkeypatch,
        datastore=FakeDatastore("LOCAL_INTERNET_RADIO"),
        primer=primer,
    )
    client.cookies.set("soundcork_account_id", ACCOUNT_ID)

    response = client.post(
        "/miniapp/play?selected_device_id=device-1&selected_content_item_id=content-1",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert primer.prime_calls == []
    assert speakers.play_calls == [(DEVICE_ID, "content-1")]
