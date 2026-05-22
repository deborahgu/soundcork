import json
import urllib.parse

from soundcork.config import Settings
from soundcork.spotify_service import SpotifyService


def test_authorize_url_uses_minimal_streaming_scope(tmp_path):
    settings = Settings(
        data_dir=str(tmp_path),
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        spotify_redirect_uri="https://soundcork.example/mgmt/spotify/callback",
    )
    service = SpotifyService(settings)

    authorize_url = service.build_authorize_url()
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorize_url).query)

    assert query["scope"] == ["streaming user-read-email user-read-private"]


def test_authorize_url_uses_configured_scope_override(tmp_path):
    settings = Settings(
        data_dir=str(tmp_path),
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        spotify_redirect_uri="https://soundcork.example/mgmt/spotify/callback",
        spotify_scopes="streaming user-read-private user-read-email user-modify-playback-state",
    )
    service = SpotifyService(settings)

    authorize_url = service.build_authorize_url()
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorize_url).query)

    assert query["scope"] == [
        "streaming user-read-private user-read-email user-modify-playback-state"
    ]


def test_get_spotify_user_id_reads_stored_spotify_user_id(tmp_path):
    spotify_dir = tmp_path / "spotify"
    spotify_dir.mkdir()
    (spotify_dir / "accounts.json").write_text(
        json.dumps([{"id": "wrong-key", "spotifyUserId": "mr.tao"}])
    )

    service = SpotifyService(Settings(data_dir=str(tmp_path)))

    assert service.get_spotify_user_id() == "mr.tao"


def test_get_spotify_user_id_returns_empty_string_without_accounts(tmp_path):
    service = SpotifyService(Settings(data_dir=str(tmp_path)))

    assert service.get_spotify_user_id() == ""
