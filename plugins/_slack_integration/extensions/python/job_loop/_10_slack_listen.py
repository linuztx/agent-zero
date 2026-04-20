"""Reconcile Slack Socket Mode listeners with enabled handlers each tick."""

import asyncio
from typing import Any

from helpers import plugins
from helpers.errors import format_error
from helpers.extension import Extension
from helpers.print_style import PrintStyle

from plugins._slack_integration.helpers.routing import PLUGIN_NAME


class SlackListenReconcile(Extension):

    async def execute(self, **kwargs: Any) -> None:
        config = plugins.get_plugin_config(PLUGIN_NAME) or {}
        enabled_globally = PLUGIN_NAME in plugins.get_enabled_plugins(None)

        from plugins._slack_integration.helpers import handler as handler_mod
        from plugins._slack_integration.helpers.socket_listener import (
            compute_config_hash, start_listener, stop_listener,
        )

        # Build desired handlers dict
        desired: dict[str, dict] = {}
        if enabled_globally:
            for h in config.get("handlers", []):
                if not h.get("enabled", False):
                    continue
                name = h.get("name", "")
                if not name:
                    continue
                desired[name] = h

        async with handler_mod._listener_lock:
            # Stop listeners not in desired or with changed config
            for name in list(handler_mod._listeners.keys()):
                handle = handler_mod._listeners[name]
                want = desired.get(name)
                if want is None:
                    await stop_listener(handle)
                    handler_mod._listeners.pop(name, None)
                    continue
                new_hash = compute_config_hash(want)
                if new_hash != handle.config_hash:
                    PrintStyle.info(f"Slack[{name}]: config changed, reconnecting")
                    await stop_listener(handle)
                    handler_mod._listeners.pop(name, None)

            # Start listeners not yet running
            for name, cfg in desired.items():
                if name in handler_mod._listeners:
                    continue
                try:
                    handle = await start_listener(cfg)
                    if handle is not None:
                        handler_mod._listeners[name] = handle
                except Exception as e:
                    PrintStyle.error(f"Slack[{name}]: start error: {format_error(e)}")
