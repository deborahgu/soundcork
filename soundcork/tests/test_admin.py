from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundcork.admin import get_admin_router
from soundcork.management import ManagementDevice, ManagementDevicesResponse
from soundcork.ui.speakers import CombinedDevice

ACCOUNT_ID = "8208423"
DEVICE_ID = "000C8A123456"
DEVICE_IP = "192.168.11.71"


class FakeDatastore:
    def list_accounts(self) -> list[str]:
        return [ACCOUNT_ID]


class FakeSpeakers:
    def __init__(self):
        self.cleared_devices: list[str] = []

    def all_devices(self) -> dict[str, CombinedDevice]:
        return {
            DEVICE_ID: CombinedDevice(
                id=DEVICE_ID,
                ip=DEVICE_IP,
                name="Kitchen",
                online=True,
                account=ACCOUNT_ID,
                in_soundcork=True,
                marge_server="Unknown",
                reachable=False,
                st_device=None,
            )
        }

    def clear_device(self, device_id: str):
        self.cleared_devices.append(device_id)


def management_devices_response(
    marge_server: str = "Bose",
) -> ManagementDevicesResponse:
    return ManagementDevicesResponse(
        devices=[
            ManagementDevice(
                device_id=DEVICE_ID,
                account_id=ACCOUNT_ID,
                reported_account_id=ACCOUNT_ID,
                name="Kitchen",
                product_code="SoundTouch10 SM2",
                ip_address=DEVICE_IP,
                stored_ip_address=DEVICE_IP,
                reported_ip_address=DEVICE_IP,
                in_soundcork=True,
                rest_reachable=True,
                marge_url="https://streaming.bose.com",
                marge_server=marge_server,
                uses_this_soundcork=False,
                source="datastore",
            )
        ]
    )


def make_client(monkeypatch, speakers: FakeSpeakers | None = None):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    app = FastAPI()
    fake_speakers = speakers or FakeSpeakers()
    app.include_router(get_admin_router(FakeDatastore(), fake_speakers))
    return TestClient(app), fake_speakers


def test_admin_shows_live_marge_and_telnet_repair_action(monkeypatch):
    monkeypatch.setattr(
        "soundcork.admin.list_management_devices",
        lambda *_args, **_kwargs: management_devices_response(),
    )
    monkeypatch.setattr(
        "soundcork.admin.addr_port_is_reachable",
        lambda _host, port, timeout=2: port == 17000,
    )

    client, _speakers = make_client(monkeypatch)
    response = client.get("/admin/")

    assert response.status_code == 200
    assert "Status guide" in response.text
    assert "REST /info" in response.text
    assert "Telnet CLIServer" in response.text
    assert "Repair Soundcork routing" in response.text
    assert f"/admin/switchToSoundcork/{DEVICE_ID}" in response.text
    assert "B0D5CC0391DB" not in response.text
    assert "Swtich" not in response.text


def test_switch_to_soundcork_uses_telnet_when_ssh_is_unavailable(monkeypatch):
    called_hosts: list[str] = []

    async def fake_non_rooted(host: str) -> bool:
        called_hosts.append(host)
        return True

    def fail_ssh(_host: str) -> bool:
        raise AssertionError("SSH repair should not be used")

    monkeypatch.setattr(
        "soundcork.admin.list_management_devices",
        lambda *_args, **_kwargs: management_devices_response(),
    )
    monkeypatch.setattr(
        "soundcork.admin.addr_port_is_reachable",
        lambda _host, port, timeout=2: port == 17000,
    )
    monkeypatch.setattr("soundcork.admin.override_speaker_config", fail_ssh)
    monkeypatch.setattr(
        "soundcork.admin.override_speaker_config_non_rooted", fake_non_rooted
    )
    monkeypatch.setattr("soundcork.admin.time.sleep", lambda _seconds: None)

    client, speakers = make_client(monkeypatch)
    response = client.post(
        f"/admin/switchToSoundcork/{DEVICE_ID}", follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == f"/admin/wait/{DEVICE_ID}/0"
    assert called_hosts == [DEVICE_IP]
    assert speakers.cleared_devices == [DEVICE_ID]
