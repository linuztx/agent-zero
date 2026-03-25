"""Per-handler WhatsApp client lifecycle management."""

import asyncio
from typing import Any

from helpers.extension import Extension
from helpers import plugins


PLUGIN_NAME: str = "_whatsapp_integration"


class WhatsAppClientManager(Extension):

    async def execute(self, **kwargs: Any) -> None:
        from plugins._whatsapp_integration.helpers.handler import (
            _client_tasks, client_lifecycle, has_session,
        )

        config = plugins.get_plugin_config(PLUGIN_NAME) or {}
        handlers = config.get("handlers", [])
        enabled_names = {
            h["name"] for h in handlers if h.get("enabled") and h.get("name")
        }

        # Stop disabled or crashed handlers
        for name in list(_client_tasks):
            if name not in enabled_names or _client_tasks[name].done():
                task = _client_tasks.pop(name, None)
                if task and not task.done():
                    task.cancel()

        # Auto-start enabled handlers with existing sessions
        for name in enabled_names:
            if name not in _client_tasks or _client_tasks[name].done():
                if has_session(name):
                    _client_tasks[name] = asyncio.create_task(
                        client_lifecycle(name)
                    )
