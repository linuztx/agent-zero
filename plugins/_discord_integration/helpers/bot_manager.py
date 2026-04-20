"""
Discord bot lifecycle manager.

Owns a registry of running BotInstance objects, creates discord.Client
subclasses with the right Intents and event handlers, and starts/stops
them as persistent asyncio tasks on the job loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from helpers.errors import format_error
from helpers.print_style import PrintStyle


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------

@dataclass
class BotInstance:
    name: str
    client: Any  # discord.Client
    task: asyncio.Task | None = None
    server_mode: str = "mention"
    welcome_enabled: bool = False
    bot_info: Any | None = None  # set in on_ready


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

_bots: dict[str, BotInstance] = {}


def get_bot(name: str) -> BotInstance | None:
    return _bots.get(name)


def get_all_bots() -> dict[str, BotInstance]:
    return _bots


# ------------------------------------------------------------------
# Bot creation
# ------------------------------------------------------------------

def _build_intents(welcome_enabled: bool) -> Any:
    import discord

    intents = discord.Intents.none()
    intents.guilds = True
    intents.messages = True
    intents.dm_messages = True
    intents.guild_messages = True
    intents.message_content = True  # privileged
    if welcome_enabled:
        intents.members = True  # privileged
    return intents


def create_bot(
    name: str,
    token: str,
    on_message: Callable[..., Awaitable[None]],
    on_member_join: Callable[..., Awaitable[None]] | None = None,
    on_interaction: Callable[..., Awaitable[None]] | None = None,
    server_mode: str = "mention",
    welcome_enabled: bool = False,
) -> BotInstance:
    import discord

    intents = _build_intents(welcome_enabled)
    client = discord.Client(intents=intents)

    instance = BotInstance(
        name=name,
        client=client,
        server_mode=server_mode,
        welcome_enabled=welcome_enabled,
    )

    # Capture user handlers under stable local names so discord.py's event
    # registration (which uses the decorated function name) doesn't shadow them.
    _on_message = on_message
    _on_member_join = on_member_join
    _on_interaction = on_interaction

    async def _ready() -> None:
        instance.bot_info = client.user
        user_repr = str(client.user) if client.user else "<unknown>"
        PrintStyle.success(f"Discord ({name}): ready as {user_repr}")

    async def _message(message: "discord.Message") -> None:
        try:
            await _on_message(message)
        except Exception as e:
            PrintStyle.error(f"Discord ({name}): on_message error: {format_error(e)}")

    client.event(_rename(_ready, "on_ready"))
    client.event(_rename(_message, "on_message"))

    if _on_member_join is not None:
        async def _member_join(member: "discord.Member") -> None:
            try:
                await _on_member_join(member)
            except Exception as e:
                PrintStyle.error(f"Discord ({name}): on_member_join error: {format_error(e)}")

        client.event(_rename(_member_join, "on_member_join"))

    if _on_interaction is not None:
        async def _interaction(interaction: "discord.Interaction") -> None:
            try:
                await _on_interaction(interaction)
            except Exception as e:
                PrintStyle.error(f"Discord ({name}): on_interaction error: {format_error(e)}")

        client.event(_rename(_interaction, "on_interaction"))

    # Stash token on the instance so callers don't have to remember it
    instance.client._a0_token = token  # type: ignore[attr-defined]

    _bots[name] = instance
    return instance


def _rename(fn: Callable[..., Awaitable[None]], new_name: str) -> Callable[..., Awaitable[None]]:
    """discord.py's @client.event binds by function __name__; rename closures so
    they register as the right event (on_ready, on_message, etc.)."""
    fn.__name__ = new_name
    return fn


# ------------------------------------------------------------------
# Start / stop
# ------------------------------------------------------------------

async def start_bot(instance: BotInstance) -> asyncio.Task:
    token = getattr(instance.client, "_a0_token", "")
    if not token:
        raise RuntimeError(f"Discord ({instance.name}): missing token on client")

    async def _run() -> None:
        try:
            PrintStyle.info(f"Discord ({instance.name}): connecting to gateway")
            await instance.client.start(token)
        except asyncio.CancelledError:
            PrintStyle.info(f"Discord ({instance.name}): gateway task cancelled")
        except Exception as e:
            PrintStyle.error(f"Discord ({instance.name}): gateway error: {format_error(e)}")

    task = asyncio.create_task(_run())
    instance.task = task
    return task


async def stop_bot(name: str) -> None:
    instance = _bots.pop(name, None)
    if not instance:
        return
    try:
        await instance.client.close()
    except Exception as e:
        PrintStyle.error(f"Discord ({name}): close error: {format_error(e)}")
    if instance.task and not instance.task.done():
        instance.task.cancel()
        try:
            await instance.task
        except asyncio.CancelledError:
            pass
    PrintStyle.info(f"Discord ({name}): stopped")


def is_alive(instance: BotInstance) -> bool:
    return bool(
        instance.task
        and not instance.task.done()
        and not getattr(instance.client, "is_closed", lambda: True)()
    )


# ------------------------------------------------------------------
# Token test (used by the settings UI)
# ------------------------------------------------------------------

async def test_token(token: str) -> tuple[bool, str, str]:
    """Validate a bot token. Returns (ok, message, client_id)."""
    import discord

    client = discord.Client(intents=discord.Intents.none())
    try:
        user = await client.login(token)
        client_id = str(user.id) if user else ""
        tag = str(user) if user else ""
        return True, f"Connected as {tag}", client_id
    except Exception as e:
        return False, format_error(e), ""
    finally:
        try:
            await client.close()
        except Exception:
            pass
