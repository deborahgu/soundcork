from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundcork.management import (
    BOSE_MARGE_URL,
    _marge_server,
    list_management_devices,
    router,
)
from soundcork.model import DeviceInfo

ACCOUNT_ID = "8208423"
DEVICE_ID = "000C8A123456"
BASE_URL = "http://unifi:8001"


def device_info_xml(
    marge_url: str = f"{BASE_URL}/marge",
    account_id: str = ACCOUNT_ID,
    ip_address: str = "192.168.11.71",
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<info deviceID="{DEVICE_ID}">
    <name>kuchyn</name>
    <type>SoundTouch10</type>
    <moduleType>SM2</moduleType>
    <networkInfo type="SCM">
        <ipAddress>{ip_address}</ipAddress>
    </networkInfo>
    <margeURL>{marge_url}</margeURL>
    <margeAccountUUID>{account_id}</margeAccountUUID>
</info>"""


def sources_xml(
    local_internet_radio_status: str | None = "READY",
    tunein_status: str | None = "READY",
) -> str:
    items = []
    if tunein_status is not None:
        items.append(f'<sourceItem source="TUNEIN" status="{tunein_status}" />')
    if local_internet_radio_status is not None:
        items.append(
            '<sourceItem source="LOCAL_INTERNET_RADIO" '
            f'status="{local_internet_radio_status}" />'
        )
    return "<sources>" + "".join(items) + "</sources>"


class FakeDatastore:
    def __init__(self):
        self.device = DeviceInfo(
            device_id=DEVICE_ID,
            product_code="SoundTouch10 SM2",
            device_serial_number="8675309",
            product_serial_number="314519",
            firmware_version="27.0.0",
            ip_address="192.168.11.71",
            name="kuchyn",
            created_on="2026-06-09T00:00:00.000+00:00",
            updated_on="2026-06-09T00:00:00.000+00:00",
        )

    def account_exists(self, account_id: str) -> bool:
        return account_id == ACCOUNT_ID

    def list_accounts(self) -> list[str]:
        return [ACCOUNT_ID]

    def list_devices(self, account_id: str) -> list[str]:
        assert account_id == ACCOUNT_ID
        return [DEVICE_ID]

    def get_device_info(self, account_id: str, device_id: str) -> DeviceInfo:
        assert account_id == ACCOUNT_ID
        assert device_id == DEVICE_ID
        return self.device


def test_marge_server_classifies_known_urls():
    assert _marge_server(None, BASE_URL) == "Unknown"
    assert _marge_server(BOSE_MARGE_URL, BASE_URL) == "Bose"
    assert _marge_server(f"{BASE_URL}/marge", BASE_URL) == "Soundcork"
    assert _marge_server("http://other.example/marge", BASE_URL) == "Other"


def test_list_management_devices_refreshes_marge_url_from_speaker_info():
    response = list_management_devices(
        FakeDatastore(),
        SimpleNamespace(base_url=BASE_URL),
        fetch_info=lambda _host: device_info_xml(),
        fetch_sources=lambda _host: sources_xml(),
    )

    device = response.devices[0]

    assert device.device_id == DEVICE_ID
    assert device.account_id == ACCOUNT_ID
    assert device.reported_account_id == ACCOUNT_ID
    assert device.rest_reachable is True
    assert device.marge_url == f"{BASE_URL}/marge"
    assert device.marge_server == "Soundcork"
    assert device.uses_this_soundcork is True
    assert device.playback_capability == "Soundcork-ready"
    assert device.internet_radio_ready is True
    assert device.source_statuses["LOCAL_INTERNET_RADIO"] == "READY"


def test_list_management_devices_reports_bose_legacy_ready_from_sources():
    response = list_management_devices(
        FakeDatastore(),
        SimpleNamespace(base_url=BASE_URL),
        fetch_info=lambda _host: device_info_xml(marge_url=BOSE_MARGE_URL),
        fetch_sources=lambda _host: sources_xml(),
    )

    device = response.devices[0]

    assert device.marge_server == "Bose"
    assert device.playback_capability == "Legacy-ready"
    assert "until reboot" in (device.playback_capability_detail or "")


def test_list_management_devices_reports_bose_needs_repair_without_radio_sources():
    response = list_management_devices(
        FakeDatastore(),
        SimpleNamespace(base_url=BASE_URL),
        fetch_info=lambda _host: device_info_xml(marge_url=BOSE_MARGE_URL),
        fetch_sources=lambda _host: sources_xml(
            local_internet_radio_status=None,
            tunein_status=None,
        ),
    )

    device = response.devices[0]

    assert device.marge_server == "Bose"
    assert device.playback_capability == "Needs repair"
    assert device.internet_radio_ready is False


def test_list_management_devices_keeps_stored_device_when_refresh_fails():
    response = list_management_devices(
        FakeDatastore(),
        SimpleNamespace(base_url=BASE_URL),
        fetch_info=lambda _host: "",
        fetch_sources=lambda _host: sources_xml(),
    )

    device = response.devices[0]

    assert device.device_id == DEVICE_ID
    assert device.rest_reachable is False
    assert device.marge_url is None
    assert device.marge_server == "Unknown"
    assert device.uses_this_soundcork is False
    assert device.playback_capability == "Unknown"


def test_list_management_devices_reports_unparseable_speaker_info():
    response = list_management_devices(
        FakeDatastore(),
        SimpleNamespace(base_url=BASE_URL),
        fetch_info=lambda _host: "<info>",
        fetch_sources=lambda _host: sources_xml(),
    )

    device = response.devices[0]

    assert device.rest_reachable is False
    assert device.error == "Unable to parse /info from 192.168.11.71"


def test_management_devices_endpoint_uses_current_speaker_info(monkeypatch):
    monkeypatch.setattr("soundcork.management.datastore", FakeDatastore())
    monkeypatch.setattr(
        "soundcork.management.settings", SimpleNamespace(base_url=BASE_URL)
    )
    monkeypatch.setattr(
        "soundcork.management.read_device_info",
        lambda _host: device_info_xml(marge_url=BOSE_MARGE_URL),
    )
    monkeypatch.setattr(
        "soundcork.management.read_runtime_sources",
        lambda _host: sources_xml(local_internet_radio_status=None, tunein_status=None),
    )

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/mgmt/devices")

    assert response.status_code == 200
    payload = response.json()
    assert payload["devices"][0]["marge_server"] == "Bose"
    assert payload["devices"][0]["uses_this_soundcork"] is False
    assert payload["devices"][0]["playback_capability"] == "Needs repair"
