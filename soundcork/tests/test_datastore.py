"""Unit tests for DataStore

These tests mock out all filesystem interactions and focus on logic."""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, call, mock_open

import pytest
from fastapi import HTTPException

from soundcork.constants import (
    DEFAULT_DATESTR,
    DEVICE_INFO_FILE,
    DEVICES_DIR,
    POWERON_FILE,
    RECENTS_FILE,
)
from soundcork.datastore import DataStore
from soundcork.model import ConfiguredSource, DeviceInfo, Preset, Recent


@pytest.fixture
def datastore(monkeypatch) -> DataStore:
    monkeypatch.setattr("soundcork.datastore.settings.data_dir", "/virtual/data")
    return DataStore()


@pytest.fixture
def sample_device() -> DeviceInfo:
    return DeviceInfo(
        device_id="abcd",
        product_code="wxyz",
        device_serial_number="8675309",
        product_serial_number="314519",
        firmware_version="1.2.3.4",
        ip_address="192.168.1.1",
        name="Cloister Room",
        created_on=DEFAULT_DATESTR,
        updated_on=DEFAULT_DATESTR,
    )


def test_poweron_devices_dir_calls_mkdir_when_missing_datastore_dir(
    datastore: DataStore, monkeypatch
):
    mkdir_mock = MagicMock()
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: False)
    monkeypatch.setattr("soundcork.datastore.mkdir", mkdir_mock)

    result = datastore.poweron_devices_dir()

    assert result == f"/virtual/data/{DEVICES_DIR}"
    mkdir_mock.assert_called_once_with(f"/virtual/data/{DEVICES_DIR}")


def test_poweron_devices_dir_skips_mkdir_when_present(
    datastore: DataStore, monkeypatch
):
    mkdir_mock = MagicMock()
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)
    monkeypatch.setattr("soundcork.datastore.mkdir", mkdir_mock)

    result = datastore.poweron_devices_dir()

    assert result == f"/virtual/data/{DEVICES_DIR}"
    mkdir_mock.assert_not_called()


def test_account_dir_raises_not_found_when_missing_datastore_dir(
    datastore: DataStore, monkeypatch
):
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: False)

    with pytest.raises(HTTPException):
        datastore.account_dir("12345")


def test_account_device_dir(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)

    result = datastore.account_device_dir("12345", sample_device.device_id)

    assert result == f"/virtual/data/12345/{DEVICES_DIR}/{sample_device.device_id}"


def test_get_device_info(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    xml = ET.fromstring(f"""
            <info deviceID="{sample_device.device_id}">
            <name>{sample_device.name}</name>
            <type>SoundTouch and Relative Dimensions in Space</type>
            <margeAccountUUID>12345</margeAccountUUID>
            <components>
                <component>
                    <componentCategory>SCM</componentCategory>
                    <softwareVersion>1</softwareVersion>
                    <serialNumber>A</serialNumber>
                </component>
                <component>
                    <componentCategory>PackagedProduct</componentCategory>
                    <serialNumber>B</serialNumber>
                </component>
            </components>
            <networkInfo type="SCM">
                <macAddress>AABB00</macAddress>
                <ipAddress>{sample_device.ip_address}</ipAddress>
            </networkInfo>
            </info>
        """)

    monkeypatch.setattr("soundcork.datastore.ET.parse", lambda _: ET.ElementTree(xml))
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)

    result = datastore.get_device_info("12345", sample_device.device_id)

    assert result.name == sample_device.name


def test_save_device_info_returns_object_and_writes_file(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    write_mock = MagicMock()
    monkeypatch.setattr(ET.ElementTree, "write", write_mock)
    monkeypatch.setattr(
        datastore,
        "account_device_dir",
        lambda *_: f"/virtual/data/12345/{DEVICES_DIR}/{sample_device.device_id}",
    )
    xml = ET.fromstring(f"""
    <info deviceID="{sample_device.device_id}">
    <name>{sample_device.name}</name>
    <type>{sample_device.product_code}</type>
    <components>
        <component>
            <componentCategory>SCM</componentCategory>
            <softwareVersion>{sample_device.firmware_version}</softwareVersion>
            <serialNumber>{sample_device.device_serial_number}</serialNumber>
        </component>
        <component>
            <componentCategory>PackagedProduct</componentCategory>
            <serialNumber>{sample_device.product_serial_number}</serialNumber>
        </component>
    </components>
    <networkInfo type="SCM">
        <macAddress>{sample_device.device_id}</macAddress>
        <ipAddress>{sample_device.ip_address}</ipAddress>
    </networkInfo>
    <createdOn>{sample_device.created_on}</createdOn>
    <updatedOn>{sample_device.updated_on}</updatedOn>
    </info>
    """)
    monkeypatch.setattr("soundcork.datastore.ET.parse", lambda _: ET.ElementTree(xml))

    updated_device = datastore.save_device_info(sample_device, "12345")
    updated_name = updated_device.name
    updated_ip = updated_device.ip_address

    assert updated_device.device_id == sample_device.device_id
    assert updated_name == sample_device.name
    assert updated_ip == sample_device.ip_address
    write_mock.assert_called_once_with(
        f"/virtual/data/12345/{DEVICES_DIR}/{sample_device.device_id}/{DEVICE_INFO_FILE}",
        xml_declaration=True,
        encoding="UTF-8",
    )


def test_device_info_path_raises_when_missing_device_dir(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: False)

    with pytest.raises(HTTPException):
        datastore.account_device_dir("12345", sample_device.device_id)


def test_create_account_calls_mkdir_if_account_dir_missing(
    datastore: DataStore, monkeypatch
):
    mkdir_mock = MagicMock()
    monkeypatch.setattr(datastore, "account_exists", lambda _: False)
    monkeypatch.setattr("soundcork.datastore.mkdir", mkdir_mock)

    created = datastore.create_account("12345")

    assert created is True
    assert mkdir_mock.call_args_list == [
        call("/virtual/data/12345"),
        call(f"/virtual/data/12345/{DEVICES_DIR}"),
    ]


def test_create_account_returns_false_if_account_dir_present(
    datastore: DataStore, monkeypatch
):
    mkdir_mock = MagicMock()
    monkeypatch.setattr(datastore, "account_exists", lambda _: True)
    monkeypatch.setattr("soundcork.datastore.mkdir", mkdir_mock)

    created = datastore.create_account("12345")

    assert created is False
    mkdir_mock.assert_not_called()


def test_add_device_returns_none_if_account_device_dir_missing(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    monkeypatch.setattr(datastore, "device_exists", lambda *_: True)

    added = datastore.add_device("12345", sample_device.device_id, sample_device)

    assert added is None


def test_add_device_calls_mkdir_and_save_info_if_account_device_dir_present(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    mkdir_mock = MagicMock()
    save_mock = MagicMock()
    monkeypatch.setattr(datastore, "device_exists", lambda *_: False)
    monkeypatch.setattr("soundcork.datastore.mkdir", mkdir_mock)
    monkeypatch.setattr(datastore, "save_device_info", save_mock)

    added = datastore.add_device("12345", sample_device.device_id, sample_device)

    assert added is not None
    mkdir_mock.assert_called_once_with(
        f"/virtual/data/12345/{DEVICES_DIR}/{sample_device.device_id}"
    )
    save_mock.assert_called_once_with(sample_device, "12345")


def test_remove_device_returns_false_if_account_device_dir_missing(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    monkeypatch.setattr(datastore, "device_exists", lambda *_: False)

    removed = datastore.remove_device("12345", sample_device.device_id)

    assert removed is False


def test_remove_device_calls_remove_and_rmdir_if_account_device_dir_present(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    remove_mock = MagicMock()
    rmdir_mock = MagicMock()
    monkeypatch.setattr(datastore, "device_exists", lambda *_: True)
    monkeypatch.setattr("soundcork.datastore.remove", remove_mock)
    monkeypatch.setattr("soundcork.datastore.rmdir", rmdir_mock)
    monkeypatch.setattr(
        datastore,
        "account_device_dir",
        lambda *_: f"/virtual/data/12345/{DEVICES_DIR}/{sample_device.device_id}",
    )

    removed = datastore.remove_device("12345", sample_device.device_id)

    assert removed is True
    remove_mock.assert_called_once_with(
        f"/virtual/data/12345/devices/{sample_device.device_id}/DeviceInfo.xml"
    )
    rmdir_mock.assert_called_once_with(
        f"/virtual/data/12345/devices/{sample_device.device_id}"
    )


def test_save_presets_constructs_xml(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    write_mock = MagicMock()
    monkeypatch.setattr(ET.ElementTree, "write", write_mock)
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)

    presets = [
        Preset(
            id="2",
            name="B",
            source="INTERNET_RADIO",
            type="uri",
            location="http://b",
            source_account="acct",
            is_presetable="true",
            created_on="",
            updated_on="",
            container_art="",
        ),
        Preset(
            id="1",
            name="A",
            source="INTERNET_RADIO",
            type="uri",
            location="http://a",
            source_account="acct",
            is_presetable="true",
            created_on="",
            updated_on="",
            container_art="",
        ),
    ]

    root = datastore.save_presets("12345", sample_device.device_id, presets)

    ids = [elem.attrib["id"] for elem in root.findall("preset")]
    assert ids == ["1", "2"]
    write_mock.assert_called_once()


def test_save_recents_constructs_xml(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    write_mock = MagicMock()
    monkeypatch.setattr(ET.ElementTree, "write", write_mock)
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)

    recents = [
        Recent(
            id="1",
            name="A",
            source="INTERNET_RADIO",
            type="uri",
            location="http://a",
            source_account="acct",
            is_presetable="true",
            created_on="",
            updated_on="",
            device_id=sample_device.device_id,
            utc_time="2026-03-06T00:00:00Z",
            container_art="bloop",
        )
    ]

    root = datastore.save_recents("12345", sample_device.device_id, recents)
    recent_elem = root.find("recent")
    content_item = recent_elem.find("contentItem") if recent_elem is not None else None
    item_name = content_item.find("itemName") if content_item is not None else None
    container_art = (
        content_item.find("containerArt") if content_item is not None else None
    )

    assert root.tag == "recents"
    assert recent_elem is not None
    assert recent_elem.attrib["deviceID"] == sample_device.device_id
    assert recent_elem.attrib["id"] == "1"
    assert content_item is not None
    assert content_item.attrib["source"] == "INTERNET_RADIO"
    assert item_name is not None
    assert item_name.text == "A"
    assert container_art is not None
    assert container_art.text == "bloop"
    write_mock.assert_called_once_with(
        f"/virtual/data/12345/{RECENTS_FILE}",
        xml_declaration=True,
        encoding="UTF-8",
    )


def test_get_presets_parses_xml_from_mocked_parse(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    xml = ET.fromstring("""
        <presets>
          <preset id="1" createdOn="" updatedOn="">
            <ContentItem source="INTERNET_RADIO" type="uri" location="http://a" sourceAccount="acct" isPresetable="true">
              <itemName>A</itemName>
              <containerArt>bloop</containerArt>
            </ContentItem>
          </preset>
          <preset id="2" createdOn="" updatedOn="">
            <ContentItem source="INTERNET_RADIO" type="uri" location="http://a" sourceAccount="acct" isPresetable="true">
              <itemName>B</itemName>
              <containerArt></containerArt>
            </ContentItem>
          </preset>
        </presets>
        """)
    monkeypatch.setattr("soundcork.datastore.ET.parse", lambda _: ET.ElementTree(xml))
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)

    loaded = datastore.get_presets("12345", sample_device.device_id)

    assert len(loaded) == 2
    assert loaded[0].name == "A"
    assert loaded[0].container_art == "bloop"
    assert loaded[1].name == "B"
    assert loaded[1].container_art == ""


def test_get_recents_parses_xml_from_mocked_parse(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    xml = ET.fromstring(f"""
        <recents>
          <recent id="1" deviceID="{sample_device.device_id}" utcTime="2026-03-05T00:00:00Z">
            <contentItem source="INTERNET_RADIO" type="uri" location="http://a" sourceAccount="acct" isPresetable="true">
              <itemName>A</itemName>
              <containerArt>bloop</containerArt>
            </contentItem>
          </recent>
          <recent id="2" deviceID="{sample_device.device_id}" utcTime="2026-03-05T00:00:00Z">
            <contentItem source="INTERNET_RADIO" type="uri" location="http://a" sourceAccount="acct" isPresetable="true">
              <itemName>B</itemName>
              <containerArt></containerArt>
            </contentItem>
          </recent>
        </recents>
        """)
    monkeypatch.setattr("soundcork.datastore.ET.parse", lambda _: ET.ElementTree(xml))
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)

    loaded = datastore.get_recents("12345", sample_device.device_id)

    assert len(loaded) == 2
    assert loaded[0].device_id == sample_device.device_id
    assert loaded[0].container_art == "bloop"
    assert loaded[1].device_id == sample_device.device_id
    assert loaded[1].container_art is None


def test_get_configured_sources_parses_and_generates_missing_id(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    xml = ET.fromstring("""
        <sources>
          <source displayName="One" secret="s1" secretType="token" id="500">
            <createdOn>1</createdOn>
            <updatedOn>2</updatedOn>
            <sourceKey account="a" type="t" />
          </source>
          <source displayName="Two" secret="s2" secretType="token">
            <createdOn>3</createdOn>
            <updatedOn>4</updatedOn>
            <sourceKey account="b" type="u" />
          </source>
        </sources>
        """)
    monkeypatch.setattr("soundcork.datastore.ET.parse", lambda _: ET.ElementTree(xml))
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)

    loaded = datastore.get_configured_sources("12345", sample_device.device_id)

    assert len(loaded) == 2
    assert isinstance(loaded[0], ConfiguredSource)
    assert loaded[0].id == "500"
    assert loaded[1].id == "100001"


def test_save_poweron_writes_xml_when_dir_exists(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    mkdir_mock = MagicMock()
    open_mock = mock_open()
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)
    monkeypatch.setattr("soundcork.datastore.mkdir", mkdir_mock)
    monkeypatch.setattr("builtins.open", open_mock)

    datastore.save_poweron(sample_device.device_id, "<updates />")

    mkdir_mock.assert_not_called()
    open_mock.assert_called_once_with(
        f"/virtual/data/devices/{sample_device.device_id}/{POWERON_FILE}", "w"
    )


def test_save_poweron_creates_dir_when_missing_and_writes_xml(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    mkdir_mock = MagicMock()
    open_mock = mock_open()
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: False)
    monkeypatch.setattr("soundcork.datastore.mkdir", mkdir_mock)
    monkeypatch.setattr("builtins.open", open_mock)

    datastore.save_poweron(sample_device.device_id, "<updates />")

    open_mock.assert_called_once_with(
        f"/virtual/data/devices/{sample_device.device_id}/{POWERON_FILE}", "w"
    )


def test_save_xml_helpers_open_files_to_write(datastore: DataStore, monkeypatch):
    open_mock = mock_open()
    monkeypatch.setattr("builtins.open", open_mock)
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)

    datastore.save_presets_xml("12345", "<presets />")
    datastore.save_recents_xml("12345", "<recents />")
    datastore.save_configured_sources_xml("12345", "<sources />")

    assert open_mock.call_count == 3


def test_etag_for_account_correctly_finds_max(datastore: DataStore, monkeypatch):
    monkeypatch.setattr("soundcork.datastore.path.exists", lambda _: True)
    monkeypatch.setattr(
        "soundcork.datastore.path.getmtime",
        lambda f: {"Presets.xml": 1.0, "Recents.xml": 2.0, "Sources.xml": 3.0}[
            f.split("/")[-1]
        ],
    )

    assert datastore.etag_for_account("12345") == 3000


def test_find_device_prefers_account_then_falls_back_poweron(
    datastore: DataStore,
    sample_device: DeviceInfo,
    monkeypatch,
):
    account_device = sample_device
    poweron_device = DeviceInfo(
        device_id="fallback",
        product_code="B",
        device_serial_number="4",
        product_serial_number="5",
        firmware_version="6",
        ip_address="10.0.0.2",
        name="",
        created_on="",
        updated_on="",
    )

    monkeypatch.setattr(datastore, "list_accounts", lambda: ["12345"])
    monkeypatch.setattr(datastore, "list_devices", lambda _: [sample_device.device_id])
    monkeypatch.setattr(datastore, "get_device_info", lambda *_: account_device)
    monkeypatch.setattr(datastore, "list_poweron_devices", lambda: ["fallback"])
    monkeypatch.setattr(datastore, "get_poweron_device_info", lambda *_: poweron_device)

    account_device_info, account = datastore.find_device(sample_device.device_id)
    poweron_device_info, poweron_account = datastore.find_device("fallback")

    assert account_device_info == account_device_info
    assert account == "12345"
    assert poweron_device_info == poweron_device
    assert poweron_account is None


def find_device_returns_none_when_no_account_or_poweron(
    datastore: DataStore, monkeypatch
):
    monkeypatch.setattr(datastore, "list_accounts", lambda: ["12345"])
    monkeypatch.setattr(datastore, "list_devices", lambda _: [])
    monkeypatch.setattr(datastore, "list_poweron_devices", lambda: [])

    found_account, account = datastore.find_device("xyz")

    assert found_account is None
    assert account is None


def test_device_info_from_device_info_xml_missing_required_fields_raises(
    datastore: DataStore, sample_device: DeviceInfo
):
    root = ET.fromstring(f'<info deviceID="{sample_device.device_id}"></info>')

    with pytest.raises(RuntimeError):
        datastore.device_info_from_device_info_xml(root)
