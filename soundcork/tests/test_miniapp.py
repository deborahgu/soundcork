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


def test_select_device_percent_encodes_unicode_cookie(monkeypatch):
    client, _speakers = make_client(monkeypatch)

    response = client.post(
        "/miniapp/select-device",
        data={"device_id": DEVICE_ID, "device_name": "ložnice"},
        follow_redirects=False,
    )

    cookies = "\n".join(set_cookie_headers(response))
    assert response.status_code == 303
    assert "soundcork_selected_device=lo%C5%BEnice" in cookies
    assert "ložnice" not in cookies


def test_dashboard_decodes_display_cookies(monkeypatch):
    client, _speakers = make_client(monkeypatch)

    response = client.get(
        "/miniapp/dashboard",
        headers={
            "Cookie": (
                f"soundcork_account_id={ACCOUNT_ID}; "
                "soundcork_account_label=%C3%9A%C4%8Det%20lo%C5%BEnice; "
                "soundcork_selected_device=lo%C5%BEnice; "
                "soundcork_selected_content_item_name=R%C3%A1dio%20Proglas; "
                f"soundcork_selected_device_id={DEVICE_ID}"
            )
        },
    )

    assert response.status_code == 200
    assert "Účet ložnice" in response.text
    assert "ložnice" in response.text
    assert "Rádio Proglas" in response.text


def test_select_content_item_plays_when_device_is_selected(monkeypatch):
    client, speakers = make_client(monkeypatch)

    response = client.post(
        "/miniapp/select-content-item",
        data={"content_item_id": "4", "content_item_name": "Rádio Proglas"},
        headers={"Cookie": f"soundcork_selected_device_id={DEVICE_ID}"},
        follow_redirects=False,
    )

    cookies = "\n".join(set_cookie_headers(response))
    assert response.status_code == 303
    assert speakers.play_calls == [(DEVICE_ID, "4")]
    assert "soundcork_selected_content_item_name=R%C3%A1dio%20Proglas" in cookies
    assert "soundcork_is_playing=true" in cookies


def test_select_content_item_without_device_only_selects(monkeypatch):
    client, speakers = make_client(monkeypatch)

    response = client.post(
        "/miniapp/select-content-item",
        data={"content_item_id": "4", "content_item_name": "Rádio Proglas"},
        follow_redirects=False,
    )

    cookies = "\n".join(set_cookie_headers(response))
    assert response.status_code == 303
    assert speakers.play_calls == []
    assert "soundcork_selected_content_item_name=R%C3%A1dio%20Proglas" in cookies
    assert "soundcork_is_playing" not in cookies


def test_select_content_item_records_failed_playback(monkeypatch):
    client, speakers = make_client(monkeypatch, FakeSpeakers(play_result=False))

    response = client.post(
        "/miniapp/select-content-item",
        data={"content_item_id": "4", "content_item_name": "Rádio Proglas"},
        headers={"Cookie": f"soundcork_selected_device_id={DEVICE_ID}"},
        follow_redirects=False,
    )

    cookies = "\n".join(set_cookie_headers(response))
    assert response.status_code == 303
    assert speakers.play_calls == [(DEVICE_ID, "4")]
    assert "soundcork_is_playing=false" in cookies
