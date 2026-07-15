import json
import urllib.parse
from types import SimpleNamespace
from typing import Any

from soundcork.config import Settings
from soundcork.zeroconf_primer import TrackedSpeaker, ZeroConfPrimer


class FakeSpotify:
    def get_spotify_user_id(self) -> str:
        return "mr.tao"

    def get_fresh_token_sync(self) -> dict:
        return {"access_token": "access-token", "expires_in": 3600}


class FakeDatastore:
    def list_accounts(self) -> list[str]:
        return ["12345"]

    def list_devices(self, account_id: str) -> list[str]:
        return ["device-1"]

    def get_device_info(self, account_id: str, device_id: str):
        return SimpleNamespace(ip_address="10.0.0.20")


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "spotify_client_id": "client-id",
        "spotify_client_secret": "client-secret",
        "spotify_zeroconf_primer_enabled": True,
        "spotify_zeroconf_prime_devices": "device-1",
    }
    values.update(overrides)
    return Settings(**values)


def test_soundcork_prime_devices_alias_is_supported(monkeypatch):
    monkeypatch.setenv("SOUNDCORK_SPOTIFY_PRIME_DEVICES", "device-1")

    loaded = Settings(_env_file=None)

    assert loaded.spotify_zeroconf_prime_devices == "device-1"


def test_primer_interval_env_var_is_supported(monkeypatch):
    monkeypatch.setenv("SPOTIFY_ZEROCONF_PRIMER_INTERVAL_SECONDS", "123")

    loaded = Settings(_env_file=None)

    assert loaded.spotify_zeroconf_primer_interval_seconds == 123


def test_speaker_allowlist_accepts_device_id_ip_or_account_device():
    primer = ZeroConfPrimer(FakeSpotify(), FakeDatastore(), settings())

    assert primer._speaker_allowed(TrackedSpeaker("12345", "device-1", "10.0.0.99"))

    primer = ZeroConfPrimer(
        FakeSpotify(),
        FakeDatastore(),
        settings(spotify_zeroconf_prime_devices="10.0.0.20"),
    )
    assert primer._speaker_allowed(TrackedSpeaker("12345", "other", "10.0.0.20"))

    primer = ZeroConfPrimer(
        FakeSpotify(),
        FakeDatastore(),
        settings(spotify_zeroconf_prime_devices="12345/device-2"),
    )
    assert primer._speaker_allowed(TrackedSpeaker("12345", "device-2", "10.0.0.21"))


def test_empty_allowlist_prevents_priming_without_network(monkeypatch):
    primer = ZeroConfPrimer(
        FakeSpotify(),
        FakeDatastore(),
        settings(spotify_zeroconf_prime_devices=""),
    )
    speaker = TrackedSpeaker("12345", "device-1", "10.0.0.20")

    def fail_send_add_user(*_):
        raise AssertionError("network should not be called without an allowlist")

    monkeypatch.setattr(
        ZeroConfPrimer, "_send_add_user", staticmethod(fail_send_add_user)
    )

    assert primer._prime_if_needed(speaker) is False


def test_prime_if_needed_sends_add_user_for_allowlisted_speaker(monkeypatch):
    primer = ZeroConfPrimer(FakeSpotify(), FakeDatastore(), settings())
    speaker = TrackedSpeaker("12345", "device-1", "10.0.0.20")
    active_users = ["", "mr.tao"]
    sent = {}

    def get_active_user(_speaker_ip):
        return active_users.pop(0)

    def send_add_user(speaker_ip, user_id, token):
        sent["speaker_ip"] = speaker_ip
        sent["user_id"] = user_id
        sent["token"] = token
        return {"status": 101}

    monkeypatch.setattr(
        ZeroConfPrimer, "_get_active_user", staticmethod(get_active_user)
    )
    monkeypatch.setattr(ZeroConfPrimer, "_send_add_user", staticmethod(send_add_user))
    monkeypatch.setattr("soundcork.zeroconf_primer.time.sleep", lambda _: None)

    assert primer._prime_if_needed(speaker) is True
    assert sent == {
        "speaker_ip": "10.0.0.20",
        "user_id": "mr.tao",
        "token": "access-token",
    }
    assert speaker.prime_failures == 0
    assert speaker.last_primed > 0


def test_prime_if_needed_skips_when_active_user_exists(monkeypatch):
    primer = ZeroConfPrimer(FakeSpotify(), FakeDatastore(), settings())
    speaker = TrackedSpeaker("12345", "device-1", "10.0.0.20")

    def fail_send_add_user(*_):
        raise AssertionError("addUser should not be sent when activeUser exists")

    monkeypatch.setattr(
        ZeroConfPrimer,
        "_get_active_user",
        staticmethod(lambda _speaker_ip: "other-user"),
    )
    monkeypatch.setattr(
        ZeroConfPrimer, "_send_add_user", staticmethod(fail_send_add_user)
    )

    assert primer._prime_if_needed(speaker) is True
    assert speaker.prime_failures == 0
    assert speaker.last_primed > 0


def test_prime_before_play_forces_add_user_for_other_active_user(monkeypatch):
    primer = ZeroConfPrimer(FakeSpotify(), FakeDatastore(), settings())
    sent = {}

    def send_add_user(speaker_ip, user_id, token):
        sent["speaker_ip"] = speaker_ip
        sent["user_id"] = user_id
        sent["token"] = token
        return {"status": 101}

    monkeypatch.setattr(
        ZeroConfPrimer,
        "_get_active_user",
        staticmethod(lambda _speaker_ip: "other-user"),
    )
    monkeypatch.setattr(ZeroConfPrimer, "_send_add_user", staticmethod(send_add_user))
    monkeypatch.setattr("soundcork.zeroconf_primer.time.sleep", lambda _: None)

    assert primer.prime_before_play("device-1", account_id="12345") is True
    assert sent == {
        "speaker_ip": "10.0.0.20",
        "user_id": "mr.tao",
        "token": "access-token",
    }
    assert primer._speakers["device-1"].ip_address == "10.0.0.20"


def test_send_add_user_posts_expected_zeroconf_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({"status": 101}).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data.decode()
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        "soundcork.zeroconf_primer.urllib.request.urlopen", fake_urlopen
    )

    result = ZeroConfPrimer._send_add_user("10.0.0.20", "mr.tao", "access-token")
    body = urllib.parse.parse_qs(captured["body"])

    assert result == {"status": 101}
    assert captured["url"] == "http://10.0.0.20:8200/zc"
    assert captured["timeout"] == 10
    assert body == {
        "action": ["addUser"],
        "userName": ["mr.tao"],
        "blob": ["access-token"],
        "tokenType": ["accesstoken"],
    }


def test_periodic_primer_does_not_start_without_allowlist():
    primer = ZeroConfPrimer(
        FakeSpotify(),
        FakeDatastore(),
        settings(spotify_zeroconf_prime_devices=""),
    )

    primer.start_periodic()

    assert primer._timer is None
