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

    # Management API authentication
    mgmt_username: str = "admin"
    mgmt_password: str = "change_me!"

    # Spotify OAuth (optional — leave empty to disable)
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = ""

    model_config = SettingsConfigDict(
        # `.env.private` takes priority over `.env.shared`
        env_file=(".env.shared", ".env.private")
    )
