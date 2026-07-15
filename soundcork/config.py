from pydantic import AliasChoices, Field
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

    # base url for the soundcork server. this should be reachable by the speakers
    base_url: str = ""

    # local directory where soundcork stores its data
    data_dir: str = ""

    # Spotify OAuth (optional — leave empty to disable)
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = ""
    spotify_scopes: str = "streaming user-read-email user-read-private"

    # Spotify ZeroConf primer (optional, disabled by default)
    spotify_zeroconf_primer_enabled: bool = False
    spotify_zeroconf_prime_devices: str = Field(
        default="",
        validation_alias=AliasChoices(
            "spotify_zeroconf_prime_devices",
            "SPOTIFY_ZEROCONF_PRIME_DEVICES",
            "SOUNDCORK_SPOTIFY_PRIME_DEVICES",
        ),
    )
    spotify_zeroconf_primer_interval_seconds: int = Field(
        default=45 * 60,
        validation_alias=AliasChoices(
            "spotify_zeroconf_primer_interval_seconds",
            "SPOTIFY_ZEROCONF_PRIMER_INTERVAL_SECONDS",
        ),
    )

    # (optional) local directory for soundcork to store detailed logs of 404 errors
    #  used for development/debugging
    unhandled_log_dir: str = ""

    model_config = SettingsConfigDict(
        # `.env.private` takes priority over `.env.shared`
        env_file=(".env.shared", ".env.private")
    )
