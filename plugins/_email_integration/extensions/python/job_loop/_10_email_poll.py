"""Lifecycle trigger — starts the dedicated email poll thread."""

from typing import Any

from helpers.extension import Extension
from helpers import plugins


PLUGIN_NAME: str = "_email_integration"


class EmailAutoPoll(Extension):

    async def execute(self, **kwargs: Any) -> None:
        config = plugins.get_plugin_config(PLUGIN_NAME) or {}
        handlers = config.get("handlers", [])
        has_enabled = any(h.get("enabled") for h in handlers if h.get("name"))
        if has_enabled:
            from plugins._email_integration.helpers.handler import ensure_poll_running
            ensure_poll_running()
