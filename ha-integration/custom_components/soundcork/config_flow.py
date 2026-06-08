"""Config flow for SoundCork integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_BASE_URL

LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL, default="http://soundcork.soundcork.svc.cluster.local:8000"): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    base_url = data[CONF_BASE_URL].rstrip("/")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{base_url}/api/v1/speakers", timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    raise CannotConnect(f"HTTP {resp.status}")
                speakers = await resp.json()
                if not speakers:
                    raise NoSpeakers("No speakers found in SoundCork")
        except aiohttp.ClientConnectorError as err:
            raise CannotConnect(str(err)) from err
        except aiohttp.ClientError as err:
            raise CannotConnect(str(err)) from err

    return {"title": f"SoundCork ({len(speakers)} speakers)", "speakers": speakers}


class SoundCorkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except NoSpeakers:
                errors["base"] = "no_speakers"
            except Exception:
                LOGGER.exception("Unexpected exception during SoundCork config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_BASE_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class CannotConnect(Exception):
    pass


class NoSpeakers(Exception):
    pass
