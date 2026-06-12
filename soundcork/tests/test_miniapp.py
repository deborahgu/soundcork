from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundcork.miniapp import get_miniapp_router, miniapp_artwork_url
from soundcork.model import Preset

ACCOUNT_ID = "8208423"
DEVICE_ID = "device-1"


class FakeDatastore:
    def __init__(self, container_art: str = "") -> None:
        self.container_art = container_art

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
                container_art=self.container_art,
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

    def get_now_playing_status(self, device_id: str):
        assert device_id == DEVICE_ID
        return None


def make_client(
    monkeypatch,
    speakers: FakeSpeakers | None = None,
    datastore: FakeDatastore | None = None,
):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    app = FastAPI()
    fake_speakers = speakers or FakeSpeakers()
    fake_datastore = datastore or FakeDatastore()
    app.include_router(
        get_miniapp_router(cast(Any, fake_datastore), cast(Any, fake_speakers))
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


def test_dashboard_proxies_tunein_preset_art(monkeypatch):
    art_url = "http://cdn-profiles.tunein.com/s123/images/logoq.png?t=1"
    client, _speakers = make_client(
        monkeypatch,
        datastore=FakeDatastore(container_art=art_url),
    )

    response = client.get(
        "/miniapp/dashboard?selected_content_item_id=4",
        headers={"Cookie": f"soundcork_account_id={ACCOUNT_ID}"},
    )

    assert response.status_code == 200
    assert f'src="{miniapp_artwork_url(art_url)}"' in response.text


def test_miniapp_artwork_url_proxies_only_tunein_artwork():
    tunein_art = "http://cdn-radiotime-logos.tunein.com/s15666q.png"
    other_art = "https://i.scdn.co/image/example"

    assert miniapp_artwork_url(tunein_art).startswith("/miniapp/artwork?url=")
    assert miniapp_artwork_url(other_art) == other_art


def test_artwork_proxy_rejects_unsupported_url(monkeypatch):
    client, _speakers = make_client(monkeypatch)

    response = client.get("/miniapp/artwork?url=http%3A%2F%2F127.0.0.1%2Fsecret.png")

    assert response.status_code == 400


def test_artwork_proxy_returns_image(monkeypatch):
    class FakeUpstream:
        headers = {"content-type": "Image/PNG; charset=binary"}
        content = b"png-bytes"

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers):
            assert url == "http://cdn-profiles.tunein.com/s123/logo.png"
            assert headers["User-Agent"] == "SoundCork miniapp artwork proxy"
            return FakeUpstream()

    monkeypatch.setattr("soundcork.miniapp.httpx.AsyncClient", FakeAsyncClient)
    client, _speakers = make_client(monkeypatch)

    response = client.get(
        "/miniapp/artwork?url=http%3A%2F%2Fcdn-profiles.tunein.com%2Fs123%2Flogo.png"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.content == b"png-bytes"
