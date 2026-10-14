"""Config flow for EnergyNib."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EnergyFlipAuthError, EnergyFlipClient, EnergyFlipError
from .const import CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS, DOMAIN, SOURCE_TYPE_HEAT

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class EnergyFlipHeatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for EnergyFlip credentials and validate them."""

    VERSION = 1

    async def _validate(self, username: str, password: str) -> tuple[str | None, dict[str, str]]:
        client = EnergyFlipClient(async_get_clientsession(self.hass), username, password)
        try:
            await client.login()
            await client.customer_overview()
        except EnergyFlipAuthError:
            return None, {"base": "invalid_auth"}
        except EnergyFlipError:
            return None, {"base": "cannot_connect"}
        if SOURCE_TYPE_HEAT not in client.sources:
            return None, {"base": "no_heat_source"}
        return client.customer_id, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            customer_id, errors = await self._validate(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                await self.async_set_unique_id(str(customer_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"EnergyFlip warmte ({user_input[CONF_USERNAME]})", data=user_input
                )
        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            _, errors = await self._validate(entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return EnergyFlipHeatOptionsFlow()


class EnergyFlipHeatOptionsFlow(OptionsFlow):
    """How much history to import on first run."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BACKFILL_DAYS, default=current): vol.All(
                        int, vol.Range(min=1, max=3650)
                    )
                }
            ),
        )
