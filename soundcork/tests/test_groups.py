import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundcork.constants import DEVICE_INFO_FILE
from soundcork.datastore import DataStore
from soundcork.groups import get_groups_router
from soundcork.groups_service import _group_id_by_name
from soundcork.marge import get_device_group_xml


def _datastore(tmp_path: Path, monkeypatch) -> DataStore:
    monkeypatch.setattr("soundcork.datastore.settings.data_dir", str(tmp_path))
    return DataStore()


def _write_st10(
    datastore: DataStore,
    account: str,
    device_id: str,
    ip_address: str,
    name: str,
    product_code: str = "SoundTouch 10 sm2",
) -> None:
    device_dir = Path(datastore.account_devices_dir(account)) / device_id
    device_dir.mkdir(parents=True, exist_ok=True)
    (device_dir / DEVICE_INFO_FILE).write_text(
        f"""
        <info deviceID="{device_id}">
            <name>{name}</name>
            <type>{product_code}</type>
            <components>
                <component>
                    <componentCategory>SCM</componentCategory>
                    <softwareVersion>27.0.0</softwareVersion>
                    <serialNumber>{device_id}</serialNumber>
                </component>
                <component>
                    <componentCategory>PackagedProduct</componentCategory>
                    <serialNumber>{device_id}</serialNumber>
                </component>
            </components>
            <networkInfo type="SCM">
                <macAddress>{device_id}</macAddress>
                <ipAddress>{ip_address}</ipAddress>
            </networkInfo>
        </info>
        """,
        encoding="utf-8",
    )


def _group_payload(
    left_id: str = "AABBCCDDEEFF",
    right_id: str = "112233445566",
) -> str:
    return f"""
    <group>
        <name>Loznice pair</name>
        <masterDeviceId>{left_id}</masterDeviceId>
        <roles>
            <groupRole>
                <deviceId>{left_id}</deviceId>
                <role>LEFT</role>
            </groupRole>
            <groupRole>
                <deviceId>{right_id}</deviceId>
                <role>RIGHT</role>
            </groupRole>
        </roles>
    </group>
    """


def test_group_datastore_roundtrip_uses_group_id_from_filename(tmp_path, monkeypatch):
    account = "12345"
    left_id = "AABBCCDDEEFF"
    right_id = "112233445566"
    datastore = _datastore(tmp_path, monkeypatch)
    _write_st10(datastore, account, left_id, "192.0.2.10", "Left")
    _write_st10(datastore, account, right_id, "192.0.2.11", "Right")

    group = datastore.group_from_xml("", ET.fromstring(_group_payload()))
    group_xml = datastore.add_group(account, group)

    group_id = group_xml.get("id")
    assert group_id
    assert (tmp_path / account / "devices" / f"Group_{group_id}.xml").exists()

    groups = datastore.list_groups(account)
    assert [group.id for group in groups] == [group_id]
    assert groups[0].left_ip == "192.0.2.10"
    assert groups[0].right_ip == "192.0.2.11"
    assert datastore.group_for_device(account, left_id).id == group_id
    assert datastore.group_to_xml(groups[0]).get("id") == group_id


def test_get_device_group_xml_returns_empty_group_for_ungrouped_st10(
    tmp_path, monkeypatch
):
    account = "12345"
    device_id = "AABBCCDDEEFF"
    datastore = _datastore(tmp_path, monkeypatch)
    _write_st10(datastore, account, device_id, "192.0.2.10", "Left")

    group_xml = get_device_group_xml(datastore, account, device_id)

    assert group_xml.tag == "group"
    assert group_xml.attrib == {}
    assert list(group_xml) == []


def test_group_service_resolves_group_id_by_name(tmp_path, monkeypatch):
    account = "12345"
    left_id = "AABBCCDDEEFF"
    right_id = "112233445566"
    datastore = _datastore(tmp_path, monkeypatch)
    _write_st10(datastore, account, left_id, "192.0.2.10", "Left")
    _write_st10(datastore, account, right_id, "192.0.2.11", "Right")
    group = datastore.group_from_xml("", ET.fromstring(_group_payload()))
    group_xml = datastore.add_group(account, group)

    assert _group_id_by_name(datastore, account, "Loznice pair") == group_xml.get("id")


def test_marge_group_routes_match_stockholm_and_speaker_shapes(tmp_path, monkeypatch):
    account = "12345"
    left_id = "AABBCCDDEEFF"
    right_id = "112233445566"
    datastore = _datastore(tmp_path, monkeypatch)
    _write_st10(datastore, account, left_id, "192.0.2.10", "Left")
    _write_st10(datastore, account, right_id, "192.0.2.11", "Right")
    app = FastAPI()
    app.include_router(get_groups_router(datastore))
    client = TestClient(app)

    created = client.post(
        f"/marge/streaming/account/{account}/group/",
        content=_group_payload(),
        headers={"Content-Type": "application/vnd.bose.streaming-v1.2+xml"},
    )

    assert created.status_code == 201
    created_xml = ET.fromstring(created.text)
    group_id = created_xml.get("id")
    assert group_id
    assert created.headers["location"].endswith(f"/group/{group_id}")

    device_group = client.get(
        f"/marge/streaming/account/{account}/device/{left_id}/group/"
    )
    assert device_group.status_code == 200
    assert ET.fromstring(device_group.text).get("id") == group_id

    groups = client.get(f"/marge/streaming/account/{account}/groups")
    assert groups.status_code == 200
    groups_xml = ET.fromstring(groups.text)
    assert groups_xml.tag == "groups"
    assert groups_xml.find("group").get("id") == group_id

    renamed = client.put(
        f"/marge/streaming/account/{account}/group/{group_id}",
        content=f"""
        <group id="{group_id}">
            <name>Renamed pair</name>
            <masterDeviceId>{left_id}</masterDeviceId>
        </group>
        """,
    )
    assert renamed.status_code == 200
    assert ET.fromstring(renamed.text).findtext("name") == "Renamed pair"

    deleted = client.delete(f"/marge/streaming/account/{account}/group/")
    assert deleted.status_code == 200
    assert datastore.list_groups(account) == []

    ungrouped = client.get(f"/marge/streaming/account/{account}/device/{left_id}/group")
    assert ungrouped.status_code == 200
    assert ET.fromstring(ungrouped.text).tag == "group"
    assert list(ET.fromstring(ungrouped.text)) == []
