import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

from soundcork.devices import _filter_items_for_sources, add_account, default_sources


def test_add_account_skips_sources_xml_when_source_copy_failed(monkeypatch):
    datastore = MagicMock()
    datastore.create_account.return_value = True
    monkeypatch.setattr("soundcork.devices.datastore", datastore)

    added = add_account(
        account_id="12345",
        recents="<recents />",
        presets="<presets />",
        sources="",
        account_name=None,
    )

    assert added is True
    datastore.save_presets_xml.assert_called_once_with("12345", "<presets />")
    datastore.save_recents_xml.assert_called_once_with("12345", "<recents />")
    datastore.save_configured_sources_xml.assert_not_called()


def test_filter_items_for_sources_removes_unavailable_recent_source():
    recents = """
        <recents>
            <recent id="1">
                <contentItem source="LOCAL_INTERNET_RADIO">
                    <itemName>Radio Proglas</itemName>
                </contentItem>
            </recent>
            <recent id="2">
                <contentItem source="SPOTIFY" sourceAccount="listener">
                    <itemName>Spotify item</itemName>
                </contentItem>
            </recent>
        </recents>
    """

    filtered = _filter_items_for_sources(
        recents, "recent", "contentItem", default_sources()
    )

    items = ET.fromstring(filtered).findall("recent")
    assert [item.findtext("contentItem/itemName") for item in items] == [
        "Radio Proglas"
    ]


def test_filter_items_for_sources_keeps_unchanged_supported_presets():
    presets = """
        <presets>
            <preset id="1">
                <ContentItem source="TUNEIN">
                    <itemName>Radio station</itemName>
                </ContentItem>
            </preset>
        </presets>
    """

    filtered = _filter_items_for_sources(
        presets, "preset", "ContentItem", default_sources()
    )

    assert filtered == presets
