from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    base_url: str = ''
    device_id: str = ''
    device_serial_number: str = ''
    product_serial_number: str = ''
    firmware_version: str = ''
    gateway_ip_address: str = ''
    ip_address: str = ''
    macaddresses: list = []
    network_connection_type: str = ''
    product_code: str = ''
    type: str = ''
    model_config = SettingsConfigDict(
        # `.env.private` takes priority over `.env.shared`
        env_file=(".env.shared", ".env.private")
    )
