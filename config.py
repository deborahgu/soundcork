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
    device_id: str = ""
    device_serial_number: str = ""
    product_serial_number: str = ""
    firmware_version: str = ""
    gateway_ip_address: str = ""
    ip_address: str = ""
    macaddresses: list = []
    network_connection_type: str = ""
    product_code: str = ""
    type: str = ""
    data_dir: str
    model_config = SettingsConfigDict(
        # `.env.private` takes priority over `.env.shared`
        env_file=(".env.shared", ".env.private")
    )
