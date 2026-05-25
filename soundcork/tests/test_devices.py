from unittest.mock import MagicMock

from soundcork.devices import add_account


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
