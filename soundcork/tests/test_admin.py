from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundcork.admin import _set_device_account, get_admin_router
from soundcork.model import Group

DEVICE_ID = "506583D69BA0"
SOURCE_ACCOUNT = "5700454"
TARGET_ACCOUNT = "8208423"


class FakeStDevice:
    def __init__(self, host: str = "192.0.2.10"):
        self.Host = host


@dataclass
class FakeCombinedDevice:
    id: str = DEVICE_ID
    ip: str = "192.0.2.10"
    name: str = "SoundTouch 10"
    online: bool = True
    account: str | None = SOURCE_ACCOUNT
    in_soundcork: bool = True
    marge_server: str = "Soundcork"
    reachable: bool = False
    st_device: FakeStDevice | None = None
    language_code: str | None = None


class FakeDatastore:
    def __init__(self):
        self.accounts = {
            SOURCE_ACCOUNT: {DEVICE_ID},
            TARGET_ACCOUNT: set(),
        }
        self.deleted_groups = []
        self.removed_devices = []
        self.group = Group(
            id="1234567",
            name="Old stereo pair",
            master_id=DEVICE_ID,
            left_id=DEVICE_ID,
            left_ip="192.0.2.10",
            right_id="304511A02B11",
            right_ip="192.0.2.11",
        )

    def list_accounts(self):
        return list(self.accounts)

    def account_exists(self, account_id):
        return account_id in self.accounts

    def device_exists(self, account_id, device_id):
        return device_id in self.accounts.get(account_id, set())

    def group_for_device(self, account_id, device_id):
        if account_id == SOURCE_ACCOUNT and self.device_exists(account_id, device_id):
            return self.group
        return None

    def delete_group(self, account_id, group_id):
        self.deleted_groups.append((account_id, group_id))

    def remove_device(self, account_id, device_id):
        self.removed_devices.append((account_id, device_id))
        self.accounts[account_id].discard(device_id)
        return True


class FakeSpeakers:
    def __init__(self, device: FakeCombinedDevice | None = None):
        self.device = device or FakeCombinedDevice(st_device=FakeStDevice())
        self.set_account_calls = []
        self.clear_device_calls = []

    def all_devices(self):
        return {self.device.id: self.device}

    def set_account(self, device_id, account_id):
        self.set_account_calls.append((device_id, account_id))
        return True

    def clear_device(self, device_id):
        self.clear_device_calls.append(device_id)


def make_client(monkeypatch, datastore=None, speakers=None):
    monkeypatch.chdir(Path(__file__).parents[1])
    monkeypatch.setattr("soundcork.admin.addr_is_reachable", lambda _: False)
    app = FastAPI()
    app.include_router(
        get_admin_router(
            datastore or FakeDatastore(),
            speakers or FakeSpeakers(),
        )
    )
    return TestClient(app)


def test_admin_shows_move_account_for_configured_device(monkeypatch):
    client = make_client(monkeypatch)

    response = client.get("/admin/")

    assert response.status_code == 200
    assert f'action="/admin/{DEVICE_ID}/setAccount"' in response.text
    assert '<input type="submit" value="Move to Account">' in response.text
    assert (
        f'<option value="{TARGET_ACCOUNT}">{TARGET_ACCOUNT}</option>' in response.text
    )
    assert (
        f'<option value="{SOURCE_ACCOUNT}">{SOURCE_ACCOUNT}</option>'
        not in response.text
    )


def test_set_device_account_imports_target_then_removes_old(monkeypatch):
    datastore = FakeDatastore()
    speakers = FakeSpeakers()
    monkeypatch.setattr("soundcork.admin.addr_is_reachable", lambda _: True)

    def add_device_by_ip(hostname, reachable):
        assert hostname == "192.0.2.10"
        assert reachable is True
        datastore.accounts[TARGET_ACCOUNT].add(DEVICE_ID)
        return True

    monkeypatch.setattr("soundcork.admin.add_device_by_ip", add_device_by_ip)

    success = _set_device_account(datastore, speakers, DEVICE_ID, TARGET_ACCOUNT)

    assert success is True
    assert speakers.set_account_calls == [(DEVICE_ID, TARGET_ACCOUNT)]
    assert datastore.device_exists(TARGET_ACCOUNT, DEVICE_ID)
    assert not datastore.device_exists(SOURCE_ACCOUNT, DEVICE_ID)
    assert datastore.deleted_groups == [(SOURCE_ACCOUNT, "1234567")]
    assert datastore.removed_devices == [(SOURCE_ACCOUNT, DEVICE_ID)]
    assert speakers.clear_device_calls == [DEVICE_ID]


def test_set_device_account_does_not_cleanup_if_import_misses_target(monkeypatch):
    datastore = FakeDatastore()
    speakers = FakeSpeakers()
    monkeypatch.setattr("soundcork.admin.addr_is_reachable", lambda _: False)
    monkeypatch.setattr("soundcork.admin.add_device_by_ip", lambda *_: True)

    success = _set_device_account(datastore, speakers, DEVICE_ID, TARGET_ACCOUNT)

    assert success is False
    assert speakers.set_account_calls == [(DEVICE_ID, TARGET_ACCOUNT)]
    assert datastore.device_exists(SOURCE_ACCOUNT, DEVICE_ID)
    assert datastore.deleted_groups == []
    assert datastore.removed_devices == []
    assert speakers.clear_device_calls == []
