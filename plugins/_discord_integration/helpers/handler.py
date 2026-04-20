"""
Discord handler — central message routing, context lifecycle, and reply sending.

Mirrors the Telegram integration's handler shape: one AgentContext per
(bot_name, user_id, channel_id) tuple, persisted across restarts via a
JSON state file.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from agent import AgentContext, UserMessage
from helpers import files, plugins, projects
from helpers import integration_commands
from helpers import message_queue as mq
from helpers.errors import format_error
from helpers.notification import (
    NotificationManager,
    NotificationPriority,
    NotificationType,
)
from helpers.persist_chat import save_tmp_chat
from helpers.print_style import PrintStyle
from initialize import initialize_agent

from plugins._discord_integration.helpers import discord_client as dc
from plugins._discord_integration.helpers.bot_manager import get_bot
from plugins._discord_integration.helpers.constants import (
    CTX_DC_ATTACHMENTS,
    CTX_DC_BOT,
    CTX_DC_BOT_CFG,
    CTX_DC_CHANNEL_ID,
    CTX_DC_GUILD_ID,
    CTX_DC_KEYBOARD,
    CTX_DC_REPLY_TO,
    CTX_DC_TYPING_STOP,
    CTX_DC_USER_ID,
    CTX_DC_USERNAME,
    DOWNLOAD_FOLDER,
    PLUGIN_NAME,
    STATE_FILE,
)

if TYPE_CHECKING:
    import discord


_chat_map_lock = threading.Lock()


# ------------------------------------------------------------------
# Persistent (bot, user, channel) → context id mapping
# ------------------------------------------------------------------

def _load_state() -> dict:
    path = files.get_abs_path(STATE_FILE)
    if os.path.isfile(path):
        try:
            return json.loads(files.read_file(path))
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    path = files.get_abs_path(STATE_FILE)
    files.make_dirs(path)
    files.write_file(path, json.dumps(state))


def _map_key(bot_name: str, user_id: int, channel_id: int) -> str:
    return f"{bot_name}:{user_id}:{channel_id}"


# ------------------------------------------------------------------
# Attachment retention
# ------------------------------------------------------------------

def cleanup_old_attachments() -> None:
    """Remove downloaded attachment files older than per-bot max age. 0 = keep forever."""
    config = plugins.get_plugin_config(PLUGIN_NAME) or {}
    bots_cfg = config.get("bots") or []
    total_removed = 0
    upload_dir = files.get_abs_path(DOWNLOAD_FOLDER)
    if not os.path.isdir(upload_dir):
        return
    for bot_cfg in bots_cfg:
        bot_name = bot_cfg.get("name", "")
        if not bot_name:
            continue
        max_age_hours = bot_cfg.get("attachment_max_age_hours", 0)
        if not max_age_hours or max_age_hours <= 0:
            continue
        prefix = f"dc_{bot_name}_"
        cutoff = time.time() - max_age_hours * 3600
        for name in os.listdir(upload_dir):
            if not name.startswith(prefix):
                continue
            path = os.path.join(upload_dir, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    total_removed += 1
            except OSError:
                pass
    if total_removed:
        PrintStyle.info(f"Discord: cleaned up {total_removed} old attachment(s)")


# ------------------------------------------------------------------
# Access control
# ------------------------------------------------------------------

def _is_allowed_user(bot_cfg: dict, user_id: int) -> bool:
    allowed = bot_cfg.get("allowed_users") or []
    if not allowed:
        return True
    user_id_str = str(user_id)
    for entry in allowed:
        if str(entry).strip() == user_id_str:
            return True
    return False


def _is_allowed_guild(bot_cfg: dict, guild_id: int | None) -> bool:
    allowed = bot_cfg.get("allowed_guilds") or []
    if not allowed:
        return True
    if guild_id is None:
        return False  # DMs don't count as any guild
    guild_id_str = str(guild_id)
    for entry in allowed:
        if str(entry).strip() == guild_id_str:
            return True
    return False


def _should_respond(bot_cfg: dict, message: "discord.Message", bot_user: "discord.User | None") -> bool:
    """Decide whether the bot should respond in this channel."""
    is_dm = message.guild is None
    server_mode = (bot_cfg.get("server_mode") or "mention").lower()

    if is_dm:
        # Server_mode=off restricts to DMs, but DMs are always allowed otherwise
        return True

    # Guild message
    if server_mode == "off":
        return False

    if not _is_allowed_guild(bot_cfg, message.guild.id):
        return False

    if server_mode == "all":
        return True

    # server_mode == "mention": reply only on @mention or reply-to-bot
    if bot_user is None:
        return False
    if bot_user in getattr(message, "mentions", []):
        return True
    ref = getattr(message, "reference", None)
    if ref is not None and getattr(ref, "resolved", None) is not None:
        referenced = ref.resolved
        if getattr(referenced, "author", None) is not None and referenced.author.id == bot_user.id:
            return True
    return False


# ------------------------------------------------------------------
# Project resolution
# ------------------------------------------------------------------

def _get_project(bot_cfg: dict, user_id: int) -> str:
    user_projects = bot_cfg.get("user_projects") or {}
    project = user_projects.get(str(user_id), "")
    if not project:
        project = bot_cfg.get("default_project", "")
    return project


def _inherit_model_override(ctx: AgentContext) -> None:
    """Copy chat_model_override from the most recent sibling context in the same project."""
    project = ctx.get_data("project")
    if not project:
        return
    try:
        from plugins._model_config.helpers.model_config import is_chat_override_allowed
        if not is_chat_override_allowed(ctx.agent0):
            return
    except Exception:
        return
    source = max(
        (
            c for c in AgentContext.all()
            if c.id != ctx.id
            and c.get_data("project") == project
            and c.get_data("chat_model_override")
        ),
        key=lambda c: c.last_message,
        default=None,
    )
    if source:
        ctx.set_data("chat_model_override", source.get_data("chat_model_override"))


# ------------------------------------------------------------------
# Context mapping
# ------------------------------------------------------------------

async def _get_or_create_context(
    bot_name: str,
    bot_cfg: dict,
    user_id: int,
    username: str,
    channel_id: int,
    guild_id: int | None,
) -> AgentContext | None:
    key = _map_key(bot_name, user_id, channel_id)

    with _chat_map_lock:
        state = _load_state()
        chats = state.setdefault("chats", {})
        ctx_id = chats.get(key)

        if ctx_id:
            ctx = AgentContext.get(ctx_id)
            if ctx:
                return ctx
            chats.pop(key, None)

        try:
            config = initialize_agent()
            display = f"@{username}" if username else str(user_id)
            ctx = AgentContext(config, name=f"Discord: {display}")

            ctx.data[CTX_DC_BOT] = bot_name
            ctx.data[CTX_DC_BOT_CFG] = bot_cfg
            ctx.data[CTX_DC_CHANNEL_ID] = channel_id
            ctx.data[CTX_DC_GUILD_ID] = guild_id
            ctx.data[CTX_DC_USER_ID] = user_id
            ctx.data[CTX_DC_USERNAME] = username or ""

            project = _get_project(bot_cfg, user_id)
            if project:
                projects.activate_project(ctx.id, project)

            _inherit_model_override(ctx)

            chats[key] = ctx.id
            _save_state(state)

            PrintStyle.success(
                f"Discord ({bot_name}): new chat {ctx.id} for user {display}"
            )
            return ctx
        except Exception as e:
            PrintStyle.error(f"Discord: failed to create context: {format_error(e)}")
            return None


# ------------------------------------------------------------------
# Typing indicator (persistent refresher)
# ------------------------------------------------------------------

def _start_typing(bot_name: str, channel_id: int) -> threading.Event:
    """Spawn a daemon thread that sends typing every 8s. Returns a stop Event.

    The loop caps itself at 10 minutes to avoid leaking threads on a stuck agent.
    """
    stop = threading.Event()

    def _run() -> None:
        async def _loop() -> None:
            deadline = time.time() + 600
            while not stop.is_set() and time.time() < deadline:
                instance = get_bot(bot_name)
                if instance is None or getattr(instance.client, "is_closed", lambda: True)():
                    return
                await dc.send_typing_once(instance.client, channel_id)
                for _ in range(16):
                    if stop.is_set():
                        return
                    await asyncio.sleep(0.5)

        try:
            asyncio.run(_loop())
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()
    return stop


# ------------------------------------------------------------------
# Incoming message formatting
# ------------------------------------------------------------------

def _format_user(message: "discord.Message") -> str:
    author = message.author
    name = getattr(author, "display_name", None) or getattr(author, "name", None) or str(author.id)
    handle = getattr(author, "name", "")
    if handle and handle != name:
        return f"{name} (@{handle})"
    return name


def _format_channel(message: "discord.Message") -> str:
    if message.guild is None:
        return "DM"
    channel = message.channel
    guild_name = message.guild.name or str(message.guild.id)
    chan_name = getattr(channel, "name", None) or str(channel.id)
    return f"#{chan_name} · {guild_name}"


async def _download_attachments(
    message: "discord.Message", bot_name: str,
) -> list[str]:
    """Download message attachments to usr/uploads and return dockerized paths."""
    atts = getattr(message, "attachments", None) or []
    if not atts:
        return []

    download_dir = files.get_abs_path(DOWNLOAD_FOLDER)
    os.makedirs(download_dir, exist_ok=True)
    download_dir_ref = files.get_abs_path_dockerized(DOWNLOAD_FOLDER)

    paths: list[str] = []
    for att in atts:
        safe_name = f"dc_{bot_name}_{uuid.uuid4().hex[:8]}_{att.filename}"
        dest = os.path.join(download_dir, safe_name)
        try:
            await att.save(dest)
            paths.append(os.path.join(download_dir_ref, safe_name))
        except Exception as e:
            PrintStyle.warning(f"Discord: attachment download failed: {format_error(e)}")
    return paths


# ------------------------------------------------------------------
# Message handler (registered with discord.Client by bot_manager)
# ------------------------------------------------------------------

async def handle_message(
    message: "discord.Message", bot_name: str, bot_cfg: dict,
) -> None:
    # Ignore bot messages (including our own)
    if message.author.bot:
        return

    # Access control
    if not _is_allowed_user(bot_cfg, message.author.id):
        return

    instance = get_bot(bot_name)
    if instance is None:
        return
    bot_user = instance.bot_info

    if not _should_respond(bot_cfg, message, bot_user):
        return

    user_id = message.author.id
    username = getattr(message.author, "name", "") or str(user_id)
    channel_id = message.channel.id
    guild_id = message.guild.id if message.guild is not None else None

    context = await _get_or_create_context(
        bot_name, bot_cfg, user_id, username, channel_id, guild_id,
    )
    if context is None:
        try:
            await message.channel.send("Failed to create chat session.")
        except Exception:
            pass
        return

    text = (message.content or "").strip()

    # Strip leading @bot mention so the command parser sees a clean text
    if bot_user is not None and text:
        mention_forms = [f"<@{bot_user.id}>", f"<@!{bot_user.id}>"]
        for form in mention_forms:
            if text.startswith(form):
                text = text[len(form):].lstrip()
                break

    # Control commands reuse the shared integration_commands module
    command_reply = integration_commands.try_handle_command(context, text)
    if command_reply is not None:
        try:
            await message.channel.send(command_reply)
        except Exception as e:
            PrintStyle.error(f"Discord: failed to send command reply: {format_error(e)}")
        return

    # Start typing refresher
    typing_stop = _start_typing(bot_name, channel_id)
    context.data[CTX_DC_TYPING_STOP] = typing_stop

    # If this message replies to a bot message, remember the source id so the
    # reply extension can reply-quote back.
    reply_to_id: int | None = None
    ref = getattr(message, "reference", None)
    if ref is not None and getattr(ref, "resolved", None) is not None:
        resolved = ref.resolved
        if (
            bot_user is not None
            and getattr(resolved, "author", None) is not None
            and resolved.author.id == bot_user.id
        ):
            reply_to_id = message.id
    context.data[CTX_DC_REPLY_TO] = reply_to_id

    # Download attachments, build prompt, hand off to the agent
    attachments = await _download_attachments(message, bot_name)

    agent = context.agent0
    user_msg = agent.read_prompt(
        "fw.discord.user_message.md",
        sender=_format_user(message),
        channel=_format_channel(message),
        body=text or "[No text content]",
    )

    msg_id = str(uuid.uuid4())
    mq.log_user_message(
        context, user_msg, attachments, message_id=msg_id, source=" (discord)",
    )
    context.communicate(UserMessage(
        message=user_msg,
        attachments=attachments,
        id=msg_id,
    ))
    save_tmp_chat(context)

    if bot_cfg.get("notify_messages", False):
        preview = (text[:80] + "...") if len(text) > 80 else text
        NotificationManager.send_notification(
            type=NotificationType.INFO,
            priority=NotificationPriority.HIGH,
            title="Discord: new message",
            message=f"From @{username}: {preview}",
            display_time=10,
            group="discord",
        )


# ------------------------------------------------------------------
# New member handler (welcome message)
# ------------------------------------------------------------------

async def handle_member_join(
    member: "discord.Member", bot_name: str, bot_cfg: dict,
) -> None:
    if not bot_cfg.get("welcome_enabled", False):
        return
    if getattr(member, "bot", False):
        return

    template = (bot_cfg.get("welcome_message") or "").strip() or "Welcome, {name}!"
    name = getattr(member, "display_name", None) or getattr(member, "name", None) or str(member.id)
    text = template.replace("{name}", name)

    # Pick a channel to announce in — system channel if set, else first sendable text channel
    guild = member.guild
    channel = getattr(guild, "system_channel", None)
    if channel is None:
        for chan in getattr(guild, "text_channels", []):
            perms = chan.permissions_for(guild.me) if guild.me is not None else None
            if perms is not None and perms.send_messages:
                channel = chan
                break
    if channel is None:
        return
    try:
        await channel.send(text)
    except Exception as e:
        PrintStyle.warning(f"Discord ({bot_name}): welcome send failed: {format_error(e)}")


# ------------------------------------------------------------------
# Interaction handler (button presses)
# ------------------------------------------------------------------

async def handle_interaction(
    interaction: "discord.Interaction", bot_name: str, bot_cfg: dict,
) -> None:
    import discord

    # Only component interactions (buttons, select menus)
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = ""
    data = interaction.data or {}
    if isinstance(data, dict):
        custom_id = str(data.get("custom_id") or "")
    if not custom_id:
        return

    try:
        await interaction.response.defer()
    except Exception:
        pass

    user = interaction.user
    if user is None:
        return
    if not _is_allowed_user(bot_cfg, user.id):
        return

    channel = interaction.channel
    if channel is None:
        return
    channel_id = channel.id
    guild_id = interaction.guild_id

    context = await _get_or_create_context(
        bot_name, bot_cfg,
        user_id=user.id,
        username=getattr(user, "name", "") or str(user.id),
        channel_id=channel_id,
        guild_id=guild_id,
    )
    if context is None:
        return

    agent = context.agent0
    user_msg = agent.read_prompt(
        "fw.discord.user_message.md",
        sender=getattr(user, "display_name", None) or getattr(user, "name", str(user.id)),
        channel=f"#{getattr(channel, 'name', str(channel_id))}",
        body=f"[Button pressed: {custom_id}]",
    )

    msg_id = str(uuid.uuid4())
    mq.log_user_message(context, user_msg, [], message_id=msg_id, source=" (discord)")
    context.communicate(UserMessage(message=user_msg, id=msg_id))
    save_tmp_chat(context)


# ------------------------------------------------------------------
# Reply sending (called from extensions)
# ------------------------------------------------------------------

async def send_discord_reply(
    context: AgentContext,
    response_text: str,
    attachments: list[str] | None = None,
    keyboard: list[list[dict]] | None = None,
) -> str | None:
    """Send a reply to the Discord channel tied to this context.

    Returns None on success, or an error string suitable for retry logic.
    """
    bot_name = context.data.get(CTX_DC_BOT)
    if not bot_name:
        return "No Discord bot configured on context"

    instance = get_bot(bot_name)
    if instance is None:
        return f"Bot '{bot_name}' not running"
    client = instance.client
    if getattr(client, "is_closed", lambda: True)():
        return f"Bot '{bot_name}' gateway is closed"

    channel_id = context.data.get(CTX_DC_CHANNEL_ID)
    if not channel_id:
        return "No channel id on context"

    # Resolve channel (cache hit first, API fallback)
    channel: Any = None
    try:
        channel = client.get_channel(int(channel_id))
        if channel is None:
            channel = await client.fetch_channel(int(channel_id))
    except Exception as e:
        return f"Failed to resolve channel {channel_id}: {format_error(e)}"
    if channel is None:
        return f"Channel {channel_id} not found"

    # Optional reply reference
    reply_to = None
    reply_to_id = context.data.get(CTX_DC_REPLY_TO)
    if reply_to_id:
        try:
            reply_to = await channel.fetch_message(int(reply_to_id))
        except Exception:
            reply_to = None

    # Attachments first; they appear above the reply text in Discord
    if attachments:
        from helpers import files as files_helper
        for path in attachments:
            local_path = files_helper.fix_dev_path(path)
            await dc.send_file(channel, local_path, reply_to=reply_to)

    # Main reply text, split to 2000-char chunks, with optional button view
    clean_text = dc.md_for_discord(response_text)
    view = dc.build_button_view(keyboard) if keyboard else None

    try:
        await dc.send_text(channel, clean_text, reply_to=reply_to, view=view)
    except Exception as e:
        return format_error(e)

    return None
