"""Discord bot lifecycle — start, restart, and stop bots based on config."""

from functools import partial
from typing import Any

from helpers import plugins
from helpers.errors import format_error
from helpers.extension import Extension
from helpers.print_style import PrintStyle

from plugins._discord_integration.helpers.dependencies import (
    ensure_dependencies,
    has_discord,
)


PLUGIN_NAME: str = "_discord_integration"


class DiscordBotManager(Extension):

    async def execute(self, **kwargs: Any) -> None:
        config = plugins.get_plugin_config(PLUGIN_NAME) or {}
        bots_cfg = config.get("bots", []) or []
        enabled_names = {
            b["name"] for b in bots_cfg
            if b.get("enabled") and b.get("name") and b.get("token")
        }

        # Skip installing discord.py on idle ticks when nothing is enabled
        if not enabled_names and not has_discord():
            return

        if enabled_names:
            ensure_dependencies()

        from plugins._discord_integration.helpers.bot_manager import (
            create_bot,
            get_all_bots,
            is_alive,
            start_bot,
            stop_bot,
        )
        from plugins._discord_integration.helpers.handler import (
            cleanup_old_attachments,
            handle_interaction,
            handle_member_join,
            handle_message,
        )

        cleanup_old_attachments()

        running = get_all_bots()

        # Stop bots that are no longer enabled
        for name in list(running.keys()):
            if name not in enabled_names:
                await stop_bot(name)

        # Start new bots (or restart if config changed)
        for bot_cfg in bots_cfg:
            name = bot_cfg.get("name", "")
            if not name or not bot_cfg.get("enabled") or not bot_cfg.get("token"):
                continue

            current_server_mode = bot_cfg.get("server_mode", "mention")
            current_welcome = bool(bot_cfg.get("welcome_enabled", False))

            if name in running:
                inst = running[name]
                unchanged = (
                    inst.server_mode == current_server_mode
                    and inst.welcome_enabled == current_welcome
                )
                if unchanged and is_alive(inst):
                    continue
                await stop_bot(name)

            try:
                on_message = partial(
                    _wrap_handler(handle_message),
                    bot_name=name, bot_cfg=bot_cfg,
                )
                on_member_join = partial(
                    _wrap_handler(handle_member_join),
                    bot_name=name, bot_cfg=bot_cfg,
                ) if current_welcome else None
                on_interaction = partial(
                    _wrap_handler(handle_interaction),
                    bot_name=name, bot_cfg=bot_cfg,
                )

                instance = create_bot(
                    name=name,
                    token=bot_cfg["token"],
                    on_message=on_message,
                    on_member_join=on_member_join,
                    on_interaction=on_interaction,
                    server_mode=current_server_mode,
                    welcome_enabled=current_welcome,
                )
                await start_bot(instance)
                PrintStyle.success(f"Discord ({name}): bot started")
            except Exception as e:
                PrintStyle.error(
                    f"Discord ({name}): failed to start: {format_error(e)}"
                )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_current_bot_cfg(bot_name: str) -> dict:
    """Fetch the latest bot config by name so handlers always use fresh settings."""
    config = plugins.get_plugin_config(PLUGIN_NAME) or {}
    for b in config.get("bots", []) or []:
        if b.get("name") == bot_name:
            return b
    return {}


def _wrap_handler(handler_fn):
    """Wrap a handler so it always reads fresh config on every event."""
    async def _wrapped(event, bot_name: str, bot_cfg: dict):
        await handler_fn(event, bot_name, _get_current_bot_cfg(bot_name) or bot_cfg)
    return _wrapped
