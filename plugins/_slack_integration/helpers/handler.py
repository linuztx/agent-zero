"""
Slack handler — orchestrates event dispatch, routing, and replies.

Requires agent context.
"""

import asyncio
import base64
import collections
import os
import uuid
from typing import Any

from agent import Agent, AgentContext, UserMessage
from helpers import files, integration_commands, message_queue as mq, plugins, runtime
from helpers.errors import format_error
from helpers.persist_chat import save_tmp_chat
from helpers.print_style import PrintStyle
from initialize import initialize_agent

from plugins._slack_integration.helpers import slack_client
from plugins._slack_integration.helpers.file_download import download_private_file
from plugins._slack_integration.helpers.markdown import md_to_slack
from plugins._slack_integration.helpers.routing import (
    CTX_SLACK_ATTACHMENTS,
    CTX_SLACK_CHANNEL_ID,
    CTX_SLACK_CHANNEL_TYPE,
    CTX_SLACK_LAST_TS,
    CTX_SLACK_REPLY_IN_THREAD,
    CTX_SLACK_TEAM_ID,
    CTX_SLACK_THINKING_ACTIVE,
    CTX_SLACK_THINKING_TS,
    CTX_SLACK_THREAD_TS,
    CTX_SLACK_USER_ID,
    CTX_SLACK_USER_NAME,
    CTX_SLACK_WORKSPACE,
    PLUGIN_NAME,
    find_context,
)


MEDIA_FOLDER = "usr/slack/files"

# Module-level state — lives here (not in the extension module) so
# reload-on-tick for extensions doesn't orphan running tasks.
_listeners: dict[str, Any] = {}   # handler_name -> socket_listener.ListenerHandle
_listener_lock = asyncio.Lock()

# Per-handler LRU dedup for (channel, ts); Slack emits app_mention
# alongside message.* for the same event.
_seen_ts: dict[str, collections.OrderedDict] = {}
_SEEN_MAX = 500


def _remember_ts(handler_name: str, key: tuple[str, str]) -> bool:
    """Return True if this (channel, ts) pair was already seen."""
    seen = _seen_ts.setdefault(handler_name, collections.OrderedDict())
    if key in seen:
        seen.move_to_end(key)
        return True
    seen[key] = None
    while len(seen) > _SEEN_MAX:
        seen.popitem(last=False)
    return False


# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------

async def dispatch_event(cfg: dict, event: dict, bot_user_id: str) -> None:
    """Entry point called by socket_listener when an events_api payload arrives."""
    if not cfg.get("enabled", False):
        return
    if PLUGIN_NAME not in plugins.get_enabled_plugins(None):
        return

    try:
        await _dispatch_message(cfg, event, bot_user_id)
    except Exception as e:
        PrintStyle.error(f"Slack dispatch error: {format_error(e)}")


async def _dispatch_message(cfg: dict, event: dict, bot_user_id: str) -> None:
    handler_name = cfg.get("name", "")
    event_type = event.get("type", "")

    # Only message and app_mention are handled; ignore other subtypes.
    if event_type not in {"message", "app_mention"}:
        return

    # Filter out bot/self/edits/deletions.
    subtype = event.get("subtype", "")
    if subtype in {"bot_message", "message_changed", "message_deleted", "channel_join", "channel_leave"}:
        return
    if event.get("bot_id"):
        return
    user = event.get("user", "") or ""
    if not user or user == bot_user_id:
        return

    channel_id = event.get("channel", "") or ""
    channel_type = event.get("channel_type", "") or ""  # "im" | "channel" | "group" | "mpim"
    ts = event.get("ts", "") or ""
    if not channel_id or not ts:
        return

    # Dedup app_mention vs message double-fire
    if _remember_ts(handler_name, (channel_id, ts)):
        PrintStyle.debug(f"Slack: deduped event {channel_id}/{ts}")
        return

    # Listen-mode filters
    is_dm = channel_type == "im"
    if is_dm and not cfg.get("listen_dm", True):
        return
    if not is_dm and not cfg.get("listen_channels", True):
        return

    # Channel events: only respond when directly mentioned or inside a thread
    # where the bot already participated (routed by find_context).
    if not is_dm and event_type == "message":
        text = event.get("text", "") or ""
        mentioned = f"<@{bot_user_id}>" in text
        thread_ts = event.get("thread_ts", "") or ""
        # If we already have a context for this thread, continue it.
        # Otherwise, only pick up channel messages if the bot was mentioned.
        if not mentioned:
            existing = find_context(handler_name, channel_id, thread_ts, channel_type)
            if not existing:
                return

    # Allow/deny list
    allowed_users = cfg.get("allowed_users") or []
    denied_users = list(cfg.get("denied_users") or [])
    denied_users.append(bot_user_id)
    if user in denied_users:
        return
    if allowed_users and user not in allowed_users:
        PrintStyle.debug(f"Slack: user {user} not in allowed_users")
        return

    allowed_channels = cfg.get("allowed_channels") or []
    if allowed_channels and not is_dm and channel_id not in allowed_channels:
        PrintStyle.debug(f"Slack: channel {channel_id} not in allowed_channels")
        return

    # Normalize thread_ts: channel mentions without a thread open one at this ts.
    thread_ts = event.get("thread_ts", "") or ""
    if not is_dm and not thread_ts:
        thread_ts = ts

    await _route_or_create(cfg, event, bot_user_id, channel_type, thread_ts)


async def _route_or_create(
    cfg: dict, event: dict, bot_user_id: str, channel_type: str, thread_ts: str,
) -> None:
    handler_name = cfg.get("name", "")
    channel_id = event.get("channel", "") or ""

    existing_id = find_context(handler_name, channel_id, thread_ts, channel_type)

    if existing_id:
        if await _handle_control_message(cfg, event, existing_id, bot_user_id):
            return
        await _add_thinking_reaction(cfg, existing_id, event)
        await _route_to_chat(cfg, event, existing_id, channel_type, thread_ts)
    else:
        await _start_new_chat(cfg, event, bot_user_id, channel_type, thread_ts)


# ------------------------------------------------------------------
# Chat creation and routing
# ------------------------------------------------------------------

async def _start_new_chat(
    cfg: dict, event: dict, bot_user_id: str, channel_type: str, thread_ts: str,
) -> None:
    from helpers import projects

    handler_name = cfg.get("name", "")
    channel_id = event.get("channel", "") or ""
    user_id = event.get("user", "") or ""
    ts = event.get("ts", "") or ""

    # Best-effort user name lookup (fallback to id)
    user_name = await _lookup_user_name(handler_name, user_id) or user_id

    agent_config = initialize_agent()
    label = f"#{channel_id}" if channel_type != "im" else user_name
    context = AgentContext(agent_config, name=f"Slack: {label[:50]}")

    context.data[CTX_SLACK_WORKSPACE] = handler_name
    context.data[CTX_SLACK_TEAM_ID] = cfg.get("team_id", "")
    context.data[CTX_SLACK_CHANNEL_ID] = channel_id
    context.data[CTX_SLACK_CHANNEL_TYPE] = channel_type
    context.data[CTX_SLACK_THREAD_TS] = "" if channel_type == "im" else thread_ts
    context.data[CTX_SLACK_USER_ID] = user_id
    context.data[CTX_SLACK_USER_NAME] = user_name
    context.data[CTX_SLACK_LAST_TS] = ts

    project = cfg.get("project", "")
    if project:
        projects.activate_project(context.id, project)

    preset = cfg.get("chat_model_preset", "")
    if preset:
        context.set_data("chat_model_override", {"preset_name": preset})

    save_tmp_chat(context)

    if await _handle_control_message(cfg, event, context.id, bot_user_id, context=context):
        return

    await _add_thinking_reaction(cfg, context.id, event)

    user_msg = await _build_user_message(context.agent0, cfg, event, channel_type)
    system_ctx = context.agent0.read_prompt("fw.slack.system_context.md")

    msg_id = str(uuid.uuid4())
    attachments = await _save_incoming_files(cfg, event.get("files") or [])
    mq.log_user_message(
        context, user_msg, attachments, message_id=msg_id, source=" (slack)",
    )
    context.communicate(UserMessage(
        message=user_msg,
        system_message=[system_ctx],
        attachments=attachments,
        id=msg_id,
    ))

    PrintStyle.success(
        f"Slack: new chat {context.id} for {user_name} in {channel_id} ({channel_type})"
    )


async def _route_to_chat(
    cfg: dict, event: dict, context_id: str, channel_type: str, thread_ts: str,
) -> None:
    context = AgentContext.get(context_id)
    if not context:
        return

    context.data[CTX_SLACK_LAST_TS] = event.get("ts", "") or ""
    # Thread ts can still be empty for DM replies; don't overwrite.
    if channel_type != "im" and thread_ts:
        context.data.setdefault(CTX_SLACK_THREAD_TS, thread_ts)

    user_msg = await _build_user_message(context.agent0, cfg, event, channel_type)
    msg_id = str(uuid.uuid4())
    attachments = await _save_incoming_files(cfg, event.get("files") or [])
    mq.log_user_message(
        context, user_msg, attachments, message_id=msg_id, source=" (slack)",
    )
    context.communicate(UserMessage(
        message=user_msg,
        attachments=attachments,
        id=msg_id,
    ))

    save_tmp_chat(context)
    PrintStyle.info(f"Slack: continuing chat {context_id}")


# ------------------------------------------------------------------
# Control commands
# ------------------------------------------------------------------

async def _handle_control_message(
    cfg: dict,
    event: dict,
    context_id: str,
    bot_user_id: str,
    *,
    context: AgentContext | None = None,
) -> bool:
    text = event.get("text", "") or ""
    # Strip leading bot mention so /project etc. trigger even in channel mentions.
    text = text.replace(f"<@{bot_user_id}>", "").strip()

    parsed = integration_commands.parse_command(text)
    if not parsed:
        return False

    context = context or AgentContext.get(context_id)
    if not context:
        return False

    response = integration_commands.try_handle_command(context, text)
    if response is None:
        return False

    web = _get_web_client(cfg.get("name", ""))
    if web is None:
        PrintStyle.warning("Slack: no active web client for control reply")
        return True

    channel_id = context.data.get(CTX_SLACK_CHANNEL_ID, "") or event.get("channel", "") or ""
    thread_ts = context.data.get(CTX_SLACK_THREAD_TS, "")
    await slack_client.post_message(web, channel_id, response, thread_ts=thread_ts)
    PrintStyle.info(f"Slack: handled control command in chat {context.id}")
    return True


# ------------------------------------------------------------------
# Reply sending
# ------------------------------------------------------------------

async def send_slack_reply(
    context: AgentContext,
    response_text: str,
    attachments: list[str] | None = None,
    in_thread: bool = True,
    keep_status: bool = False,
) -> str | None:
    handler_name = context.data.get(CTX_SLACK_WORKSPACE, "")
    channel_id = context.data.get(CTX_SLACK_CHANNEL_ID, "")
    thread_ts = context.data.get(CTX_SLACK_THREAD_TS, "") if in_thread else ""
    if not channel_id:
        return "No Slack channel id"

    web = _get_web_client(handler_name)
    if web is None:
        return "Slack listener not running"

    text = md_to_slack(response_text or "")

    result = await slack_client.post_message(web, channel_id, text, thread_ts=thread_ts)
    if not result.get("ok", False):
        return result.get("error", "unknown error")

    if attachments:
        cfg = _get_handler_config(handler_name) or {}
        max_mb = int(cfg.get("max_upload_size_mb", 25) or 25)
        max_bytes = max_mb * 1024 * 1024
        host_paths = await _read_attachments_to_host(attachments)
        for host_path in host_paths:
            try:
                if os.path.getsize(host_path) > max_bytes:
                    PrintStyle.warning(f"Slack: skipping oversized attachment {host_path}")
                    continue
                up = await slack_client.upload_file(
                    web, channel_id, host_path,
                    filename=os.path.basename(host_path),
                    thread_ts=thread_ts,
                )
                if not up.get("ok", False):
                    PrintStyle.warning(f"Slack: attachment error: {up.get('error')}")
            except Exception as e:
                PrintStyle.warning(f"Slack: attachment error: {e}")

    if not keep_status:
        await _remove_thinking_reaction(context)

    return None


# ------------------------------------------------------------------
# Reactions
# ------------------------------------------------------------------

async def _add_thinking_reaction(cfg: dict, context_id: str, event: dict) -> None:
    if not cfg.get("use_thinking_reaction", True):
        return
    context = AgentContext.get(context_id)
    if not context:
        return
    web = _get_web_client(cfg.get("name", ""))
    if web is None:
        return
    channel_id = event.get("channel", "") or ""
    ts = event.get("ts", "") or ""
    if not channel_id or not ts:
        return
    emoji = (cfg.get("thinking_emoji") or "thinking_face").strip(":")
    result = await slack_client.reactions_add(web, channel_id, ts, emoji)
    # already_reacted is fine — treat as active for cleanup
    if result.get("ok", False) or result.get("error") == "already_reacted":
        context.data[CTX_SLACK_THINKING_ACTIVE] = True
        context.data[CTX_SLACK_THINKING_TS] = ts


async def _remove_thinking_reaction(context: AgentContext) -> None:
    if not context.data.get(CTX_SLACK_THINKING_ACTIVE):
        return
    handler_name = context.data.get(CTX_SLACK_WORKSPACE, "")
    web = _get_web_client(handler_name)
    if web is None:
        return
    channel_id = context.data.get(CTX_SLACK_CHANNEL_ID, "")
    ts = context.data.get(CTX_SLACK_THINKING_TS, "")
    if not channel_id or not ts:
        return
    cfg = _get_handler_config(handler_name) or {}
    emoji = (cfg.get("thinking_emoji") or "thinking_face").strip(":")
    await slack_client.reactions_remove(web, channel_id, ts, emoji)
    context.data[CTX_SLACK_THINKING_ACTIVE] = False
    context.data[CTX_SLACK_THINKING_TS] = ""


# ------------------------------------------------------------------
# Attachments (runtime ↔ host via RFC base64)
# ------------------------------------------------------------------

async def _read_attachments_to_host(paths: list[str]) -> list[str]:
    from plugins._slack_integration.helpers.attachment_reader import read_attachment

    host_paths: list[str] = []
    for path in paths:
        data = await runtime.call_development_function(read_attachment, path)
        if data["error"]:
            PrintStyle.warning(f"Slack attachment: {data['error']}")
            continue
        host_path = os.path.join(files.get_abs_path(MEDIA_FOLDER), data["name"])
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        with open(host_path, "wb") as f:
            f.write(base64.b64decode(data["content_b64"]))
        host_paths.append(host_path)
    return host_paths


async def _save_incoming_files(cfg: dict, slack_files: list[dict]) -> list[str]:
    """Download each Slack file with the bot token and write into the runtime."""
    from plugins._slack_integration.helpers.attachment_writer import write_attachment

    if not slack_files:
        return []

    bot_token = cfg.get("bot_token", "") or ""
    max_mb = int(cfg.get("max_upload_size_mb", 25) or 25)
    max_bytes = max_mb * 1024 * 1024

    runtime_paths: list[str] = []
    for f in slack_files:
        url = f.get("url_private_download") or f.get("url_private") or ""
        name = f.get("name") or f.get("id") or "file"
        if not url or not bot_token:
            continue
        content, err = await download_private_file(url, bot_token, max_bytes)
        if err:
            PrintStyle.warning(f"Slack file download: {err}")
            continue
        content_b64 = base64.b64encode(content).decode()
        rel_path = os.path.join(MEDIA_FOLDER, name)
        result = await runtime.call_development_function(
            write_attachment, rel_path, content_b64,
        )
        if result.get("error"):
            PrintStyle.warning(f"Slack file save: {result['error']}")
            # Fallback: write to host-side cache so the agent can still see it.
            host_path = os.path.join(files.get_abs_path(MEDIA_FOLDER), name)
            os.makedirs(os.path.dirname(host_path), exist_ok=True)
            with open(host_path, "wb") as hf:
                hf.write(content)
            runtime_paths.append(host_path)
        else:
            runtime_paths.append(result["path"])
    return runtime_paths


# ------------------------------------------------------------------
# User/message builders
# ------------------------------------------------------------------

async def _lookup_user_name(handler_name: str, user_id: str) -> str:
    if not user_id:
        return ""
    web = _get_web_client(handler_name)
    if web is None:
        return ""
    try:
        info = await slack_client.users_info(web, user_id)
        if not info.get("ok", False):
            return ""
        profile = info.get("user", {}) or {}
        return (
            profile.get("real_name")
            or profile.get("profile", {}).get("display_name")
            or profile.get("name")
            or ""
        )
    except Exception:
        return ""


async def _build_user_message(
    agent: Agent, cfg: dict, event: dict, channel_type: str,
) -> str:
    handler_name = cfg.get("name", "")
    user_id = event.get("user", "") or ""
    user_name = await _lookup_user_name(handler_name, user_id) or user_id
    body = event.get("text", "") or ""

    is_dm = channel_type == "im"
    prompt = "fw.slack.user_message.md" if is_dm else "fw.slack.user_message_channel.md"
    return agent.read_prompt(
        prompt,
        sender_name=user_name,
        sender_user_id=user_id,
        channel_id=event.get("channel", "") or "",
        channel_type=channel_type,
        thread_ts=event.get("thread_ts", "") or event.get("ts", "") or "",
        ts=event.get("ts", "") or "",
        body=body,
    )


# ------------------------------------------------------------------
# Listener access helpers
# ------------------------------------------------------------------

def _get_web_client(handler_name: str):
    handle = _listeners.get(handler_name)
    if handle is None:
        return None
    return getattr(handle, "web", None)


def _get_handler_config(handler_name: str) -> dict | None:
    config = plugins.get_plugin_config(PLUGIN_NAME) or {}
    for h in config.get("handlers", []):
        if h.get("name") == handler_name:
            return h
    return None
