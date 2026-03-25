"""
WhatsApp handler -- orchestrates client lifecycle, message routing, and reply.

Requires agent context.
"""

import asyncio
import base64
from functools import partial
from typing import Any

from agent import Agent, AgentContext, UserMessage
from helpers import plugins
from helpers import runtime
from helpers import message_queue as mq
from helpers.persist_chat import save_tmp_chat
from helpers.print_style import PrintStyle
from helpers.errors import format_error
from initialize import initialize_agent

from plugins._whatsapp_integration.helpers.whatsapp_client import (
    InboundMessage,
    create_client,
    connect_client,
    disconnect_client,
    logout_client,
    send_message,
    send_document,
    SESSION_FOLDER,
)


PLUGIN_NAME = "_whatsapp_integration"
DOWNLOAD_FOLDER = "usr/whatsapp/attachments"

# Persistent context data keys
CTX_WA_HANDLER = "whatsapp_handler"
CTX_WA_CHAT_JID = "whatsapp_chat_jid"
CTX_WA_SENDER_JID = "whatsapp_sender_jid"
CTX_WA_SENDER_NAME = "whatsapp_sender_name"

# Transient
CTX_WA_ATTACHMENTS = "_whatsapp_response_attachments"
CTX_SEND_FAILURES = "_whatsapp_send_failures"

RETRY_BACKOFF = 10


# ------------------------------------------------------------------
# Module-level state (persists across extension reloads)
# ------------------------------------------------------------------

_client_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
_clients: dict[str, Any] = {}  # handler_name -> NewAClient
_qr_data: dict[str, bytes] = {}  # handler_name -> latest QR bytes


# ------------------------------------------------------------------
# Client lifecycle
# ------------------------------------------------------------------

async def start_client(handler_cfg: dict) -> None:
    import os
    from helpers import files

    name = handler_cfg.get("name", "default")

    # Ensure session directory exists
    session_dir = files.get_abs_path(SESSION_FOLDER)
    os.makedirs(session_dir, exist_ok=True)
    db_path = f"{session_dir}/{name}.db"

    PrintStyle.info(f"WhatsApp: creating client ({name}) with db: {db_path}")

    client = create_client(name, db_path)

    async def on_qr(qr_bytes: bytes) -> None:
        _qr_data[name] = qr_bytes
        PrintStyle.info(f"WhatsApp: QR code stored for {name} ({len(qr_bytes)} bytes) - scan in WebUI settings")

    async def on_connected() -> None:
        _qr_data.pop(name, None)
        PrintStyle.success(f"WhatsApp: handler {name} connected")

    callback = partial(_on_message, handler_cfg)
    _clients[name] = client

    PrintStyle.info(f"WhatsApp: starting client ({name})")

    try:
        await connect_client(client, callback, on_qr, on_connected)
    finally:
        _clients.pop(name, None)
        _qr_data.pop(name, None)
        try:
            await disconnect_client(client)
        except BaseException:
            pass


async def stop_client(handler_name: str, logout: bool = False) -> None:
    task = _client_tasks.pop(handler_name, None)
    if task and not task.done():
        task.cancel()
    client = _clients.pop(handler_name, None)
    if client:
        try:
            if logout:
                await logout_client(client)
            else:
                await disconnect_client(client)
        except BaseException:
            pass
    _qr_data.pop(handler_name, None)


def remove_session(handler_name: str) -> None:
    """Delete session database files for a removed handler."""
    import os
    from helpers import files

    session_dir = files.get_abs_path(SESSION_FOLDER)
    db_path = f"{session_dir}/{handler_name}.db"

    # Remove main db and any WAL/SHM sidecar files
    for pattern in [db_path, f"{db_path}-wal", f"{db_path}-shm"]:
        if os.path.exists(pattern):
            try:
                os.remove(pattern)
                PrintStyle.info(f"WhatsApp: removed session file {pattern}")
            except OSError as e:
                PrintStyle.error(f"WhatsApp: failed to remove {pattern}: {e}")


# ------------------------------------------------------------------
# QR code access (for WebUI API)
# ------------------------------------------------------------------

def get_qr_data(handler_name: str) -> bytes | None:
    return _qr_data.get(handler_name)


def is_connected(handler_name: str) -> bool:
    client = _clients.get(handler_name)
    return bool(client and client.connected)


# ------------------------------------------------------------------
# Session and config helpers
# ------------------------------------------------------------------

def has_session(handler_name: str) -> bool:
    import os
    from helpers import files
    session_dir = files.get_abs_path(SESSION_FOLDER)
    return os.path.exists(f"{session_dir}/{handler_name}.db")


def get_handler_cfg(handler_name: str) -> dict | None:
    config = plugins.get_plugin_config(PLUGIN_NAME) or {}
    for h in config.get("handlers", []):
        if h.get("name") == handler_name:
            return h
    return None


async def client_lifecycle(
    handler_name: str,
    initial_cfg: dict | None = None,
) -> None:
    """Run client with retry loop. Checks saved config each iteration."""
    first = True
    while True:
        if first and initial_cfg:
            handler_cfg = initial_cfg
            first = False
        else:
            handler_cfg = get_handler_cfg(handler_name)
        if not handler_cfg or not handler_cfg.get("enabled"):
            break
        try:
            await start_client(handler_cfg)
        except asyncio.CancelledError:
            PrintStyle.info(f"WhatsApp: client task cancelled for {handler_name}")
            break
        except Exception as e:
            PrintStyle.error(
                f"WhatsApp: client error ({handler_name}): {format_error(e)}"
            )
        # Always wait before retry (gives neonize time to release DB/resources)
        await asyncio.sleep(RETRY_BACKOFF)


# ------------------------------------------------------------------
# Inbound message handling
# ------------------------------------------------------------------

async def _on_message(
    handler_cfg: dict,
    msg: InboundMessage,
) -> None:
    try:
        await _process_message(handler_cfg, msg)
    except Exception as e:
        PrintStyle.error(f"WhatsApp: message handler error: {format_error(e)}")


async def _process_message(
    handler_cfg: dict,
    msg: InboundMessage,
) -> None:
    # Whitelist check (phone numbers)
    allowed = handler_cfg.get("allowed_users") or []
    if allowed:
        sender_number = msg.sender_jid.split("@")[0]
        if sender_number not in [str(u) for u in allowed]:
            return

    # Group check
    if msg.chat_type != "private":
        if not handler_cfg.get("allow_groups", False):
            return

    # Commands
    if msg.is_command and msg.command == "start":
        await _handle_start(handler_cfg, msg)
        return
    if msg.is_command and msg.command == "reset":
        await _handle_reset(handler_cfg, msg)
        return

    # Route to existing or new context
    handler_name = handler_cfg.get("name", "default")
    context_id = _find_handler_chat(handler_name, msg.chat_jid)

    if context_id:
        await _route_to_chat(handler_cfg, msg, context_id)
    else:
        await _start_new_chat(handler_cfg, msg)


# ------------------------------------------------------------------
# Command handlers
# ------------------------------------------------------------------

async def _handle_start(handler_cfg: dict, msg: InboundMessage) -> None:
    handler_name = handler_cfg.get("name", "default")
    context_id = _find_handler_chat(handler_name, msg.chat_jid)

    if not context_id:
        await _start_new_chat(handler_cfg, msg, send_welcome=True)
    else:
        client = _clients.get(handler_name)
        if client:
            await send_message(client, msg.chat_jid, _welcome_text())


async def _handle_reset(handler_cfg: dict, msg: InboundMessage) -> None:
    from helpers.persist_chat import remove_chat

    handler_name = handler_cfg.get("name", "default")
    context_id = _find_handler_chat(handler_name, msg.chat_jid)

    if context_id:
        ctx = AgentContext.get(context_id)
        if ctx:
            ctx.reset()
            AgentContext.remove(context_id)
            remove_chat(context_id)
            PrintStyle.info(f"WhatsApp: reset chat {context_id}")

    client = _clients.get(handler_name)
    if client:
        await send_message(client, msg.chat_jid, _reset_text())


def _welcome_text() -> str:
    return (
        "Welcome to Agent Zero\n"
        "Send any message to start a conversation\n"
        "Use /reset to clear context and start fresh"
    )


def _reset_text() -> str:
    return "Context cleared\nSend any message to start a new conversation"


# ------------------------------------------------------------------
# Chat creation and routing
# ------------------------------------------------------------------

async def _start_new_chat(
    handler_cfg: dict,
    msg: InboundMessage,
    send_welcome: bool = False,
) -> None:
    from helpers import projects

    handler_name = handler_cfg.get("name", "default")

    config = initialize_agent()
    context = AgentContext(config, name=f"WhatsApp: {msg.sender_name}")

    context.data[CTX_WA_HANDLER] = handler_name
    context.data[CTX_WA_CHAT_JID] = msg.chat_jid
    context.data[CTX_WA_SENDER_JID] = msg.sender_jid
    context.data[CTX_WA_SENDER_NAME] = msg.sender_name

    project = handler_cfg.get("project", "")
    if project:
        projects.activate_project(context.id, project)

    save_tmp_chat(context)

    if send_welcome:
        client = _clients.get(handler_name)
        if client:
            await send_message(client, msg.chat_jid, _welcome_text())

    # Only send to agent if there's actual content (not just /start)
    if msg.is_command and msg.command == "start" and not _has_content_after_command(msg):
        PrintStyle.success(f"WhatsApp: new chat {context.id} for {msg.sender_name}")
        return

    user_msg = _build_user_message(context.agent0, msg, handler_cfg)
    system_ctx = context.agent0.read_prompt("fw.whatsapp.system_context.md")

    mq.log_user_message(context, user_msg, msg.attachments or [], source=" (whatsapp)")
    context.communicate(UserMessage(
        message=user_msg,
        system_message=[system_ctx],
        attachments=msg.attachments,
    ))

    PrintStyle.success(f"WhatsApp: new chat {context.id} for {msg.sender_name}")


async def _route_to_chat(
    handler_cfg: dict,
    msg: InboundMessage,
    context_id: str,
) -> None:
    context = AgentContext.get(context_id)
    if not context:
        await _start_new_chat(handler_cfg, msg)
        return

    # Update sender info in case it changed
    context.data[CTX_WA_SENDER_NAME] = msg.sender_name

    user_msg = _build_user_message(context.agent0, msg, handler_cfg)
    mq.log_user_message(context, user_msg, msg.attachments or [], source=" (whatsapp)")
    context.communicate(UserMessage(
        message=user_msg,
        attachments=msg.attachments,
    ))

    save_tmp_chat(context)
    PrintStyle.info(f"WhatsApp: continuing chat {context_id}")


# ------------------------------------------------------------------
# Chat discovery
# ------------------------------------------------------------------

def _find_handler_chat(handler_name: str, chat_jid: str) -> str | None:
    for ctx_id, ctx in AgentContext._contexts.items():
        if not isinstance(ctx, AgentContext):
            continue
        data = ctx.data
        if data.get(CTX_WA_HANDLER) != handler_name:
            continue
        if data.get(CTX_WA_CHAT_JID) != chat_jid:
            continue
        return ctx_id
    return None


# ------------------------------------------------------------------
# Message builders
# ------------------------------------------------------------------

def _build_user_message(agent: Agent, msg: InboundMessage, handler_cfg: dict) -> str:
    text = msg.text or ""
    text = agent.read_prompt(
        "fw.whatsapp.user_message.md",
        sender_name=msg.sender_name,
        sender_jid=msg.sender_jid,
        text=text,
    )
    instructions = handler_cfg.get("agent_instructions", "")
    if instructions:
        text += agent.read_prompt(
            "fw.whatsapp.user_message_instructions.md", instructions=instructions,
        )
    return text


def _has_content_after_command(msg: InboundMessage) -> bool:
    parts = (msg.text or "").split(maxsplit=1)
    return len(parts) > 1 or bool(msg.attachments)


# ------------------------------------------------------------------
# Reply sending (called from process_chain_end and tool_execute_after)
# ------------------------------------------------------------------

async def send_whatsapp_reply(
    context: AgentContext,
    response_text: str,
    attachments: list[str] | None = None,
) -> str | None:
    handler_name = context.data.get(CTX_WA_HANDLER)
    if not handler_name:
        return "No whatsapp handler configured"

    chat_jid = context.data.get(CTX_WA_CHAT_JID)
    if not chat_jid:
        return "No chat_jid in context"

    client = _clients.get(handler_name)
    if not client:
        return f"Client not running for handler '{handler_name}'"

    try:
        await send_message(client, chat_jid, response_text)

        # Send file attachments
        attachment_data = await _read_attachments_via_rfc(attachments)
        for name, content in attachment_data:
            await send_document(client, chat_jid, content, name)

        return None
    except Exception as e:
        error = format_error(e)
        PrintStyle.error(f"WhatsApp send error: {error}")
        return error


# ------------------------------------------------------------------
# Attachment reading (via RFC into execution runtime)
# ------------------------------------------------------------------

async def _read_attachments_via_rfc(
    paths: list[str] | None,
) -> list[tuple[str, bytes]]:
    if not paths:
        return []

    from plugins._whatsapp_integration.helpers.attachment_reader import read_attachment

    results: list[tuple[str, bytes]] = []
    for path in paths:
        data = await runtime.call_development_function(read_attachment, path)
        if data["error"]:
            PrintStyle.error(f"WhatsApp attachment: {data['error']}")
            continue
        results.append((data["name"], base64.b64decode(data["content_b64"])))
    return results
