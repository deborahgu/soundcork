import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from soundcork.config import Settings

security = HTTPBasic()
settings = Settings()


def verify_credentials(
    credentials: HTTPBasicCredentials = Depends(security),
) -> str:
    """Verify HTTP Basic Auth credentials for management endpoints.

    Returns the username on success, raises 401 on failure.
    """
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.mgmt_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.mgmt_password.encode("utf-8"),
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
