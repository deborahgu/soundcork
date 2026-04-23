from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Create the settings.

    Don't populate here. The variables are only declared to make life
    easier for IDE autocomplete. Populate in .env.shared -- or, if
    committing to source control, .env.private (which is in the
    .gitignore).

    Source for each of these strings:

    Unless otherwise specified all files are on you speaker in:
    /var/volatile/lib/Bose/PersistenceDataRoot/BoseApp-Persistence/1

    - device_id: Recents.xml

    """

    base_url: str = ""
    data_dir: str = ""
    soundcork_mode: str = "local"
    soundcork_log_dir: str = "./logs/traffic"

    # Management API authentication
    mgmt_username: str = "admin"
    mgmt_password: str = "change_me!"

    # Debug logging for API research
    log_request_body: bool = False
    log_request_headers: bool = False

    # ZeroConf primer: periodic push of Spotify tokens to speakers
    # Disable if speakers self-prime at boot via /mnt/nv/rc.local
    zeroconf_primer_enabled: bool = True

    # OIDC authentication (optional — when all three are set, OIDC is enabled)
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer_url and self.oidc_client_id and self.oidc_client_secret)

    # Spotify OAuth
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "ueberboese-login://spotify"

    model_config = SettingsConfigDict(
        # `.env.private` takes priority over `.env.shared`
        env_file=(".env.shared", ".env.private")
    )
