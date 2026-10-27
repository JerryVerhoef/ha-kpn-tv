"""Config flow voor KPN TV."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .channels import ChannelListError, parse_channels
from .const import (
    CONF_ADB_ENTITY,
    CONF_BOOT_DELAY,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    CONF_CHANNELS,
    CONF_KEY_DELAY,
    CONF_REMOTE,
    CONF_SEND_ENTER,
    DEFAULT_BOOT_DELAY,
    DEFAULT_CHANNELS,
    DEFAULT_KEY_DELAY,
    DEFAULT_NAME,
    DEFAULT_SEND_ENTER,
    DOMAIN,
)

DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_CHANNELS: DEFAULT_CHANNELS,
    CONF_KEY_DELAY: DEFAULT_KEY_DELAY,
    CONF_BOOT_DELAY: DEFAULT_BOOT_DELAY,
    CONF_SEND_ENTER: DEFAULT_SEND_ENTER,
    CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
}


def _options_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_CHANNELS, default=current.get(CONF_CHANNELS, DEFAULT_CHANNELS)
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            vol.Required(
                CONF_KEY_DELAY, default=current.get(CONF_KEY_DELAY, DEFAULT_KEY_DELAY)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=2, step=0.1, unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_BOOT_DELAY,
                default=current.get(CONF_BOOT_DELAY, DEFAULT_BOOT_DELAY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=60, step=1, unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_SEND_ENTER,
                default=current.get(CONF_SEND_ENTER, DEFAULT_SEND_ENTER),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ADB_ENTITY,
                description={"suggested_value": current.get(CONF_ADB_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="media_player", integration="androidtv"
                )
            ),
            vol.Required(
                CONF_POLL_INTERVAL,
                default=current.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=3, max=120, step=1, unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


class KpnTvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Koppel een KPN TV+ Box via zijn bestaande remote-entity."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            remote = user_input[CONF_REMOTE]
            await self.async_set_unique_id(remote)
            self._abort_if_unique_id_configured()
            if self.hass.states.get(remote) is None:
                errors[CONF_REMOTE] = "remote_not_found"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_NAME: user_input[CONF_NAME], CONF_REMOTE: remote},
                    options=dict(DEFAULT_OPTIONS),
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_REMOTE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="remote")
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return KpnTvOptionsFlow()


class KpnTvOptionsFlow(OptionsFlow):
    """Zenderlijst en timing aanpassen."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"line": ""}
        if user_input is not None:
            try:
                parsed = parse_channels(user_input[CONF_CHANNELS])
            except ChannelListError as err:
                errors[CONF_CHANNELS] = "invalid_channels"
                placeholders["line"] = str(err)
            else:
                if not parsed:
                    errors[CONF_CHANNELS] = "no_channels"
                else:
                    return self.async_create_entry(data=user_input)

        current = {**DEFAULT_OPTIONS, **self.config_entry.options, **(user_input or {})}
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current),
            errors=errors,
            description_placeholders=placeholders,
        )
