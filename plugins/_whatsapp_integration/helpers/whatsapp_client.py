"""
WhatsApp client wrapper using neonize (async).

No agent/tool dependencies.
"""

import base64
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import asyncio

from neonize.aioze.client import NewAClient
from neonize.aioze.events import (
    ConnectedEv, MessageEv, KeepAliveTimeoutEv, KeepAliveRestoredEv,
)
from neonize.utils.jid import Jid2String


DOWNLOAD_FOLDER = "usr/whatsapp/attachments"
SESSION_FOLDER = "usr/whatsapp/sessions"


# ------------------------------------------------------------------
# Data models
# ------------------------------------------------------------------

@dataclass
class InboundMessage:
    chat_jid: str
    sender_jid: str
    sender_name: str
    text: str
    message_id: str
    chat_type: str
    attachments: list[str] = field(default_factory=list)
    is_command: bool = False
    command: str = ""
    raw_event: Any = None


# ------------------------------------------------------------------
# Client lifecycle
# ------------------------------------------------------------------

def create_client(name: str, db_path: str) -> NewAClient:
    return NewAClient(db_path)


MAX_KEEPALIVE_FAILURES = 3


async def connect_client(
    client: NewAClient,
    message_callback: Callable[["InboundMessage"], Awaitable[None]],
    qr_callback: Callable[[bytes], Awaitable[None]],
    connected_callback: Callable[[], Awaitable[None]] | None = None,
) -> None:
    from helpers.print_style import PrintStyle

    connection_dead = asyncio.Event()
    keepalive_failures = 0

    @client.event(ConnectedEv)
    async def on_connected(_client: NewAClient, _ev: ConnectedEv) -> None:
        PrintStyle.success("WhatsApp: connected successfully")
        if connected_callback:
            await connected_callback()

    @client.event(MessageEv)
    async def on_message(_client: NewAClient, msg_event: MessageEv) -> None:
        try:
            if msg_event.Info.MessageSource.IsFromMe:
                return
            msg = await extract_message(_client, msg_event)
            if msg:
                await message_callback(msg)
        except Exception as e:
            from helpers.errors import format_error
            PrintStyle.error(f"WhatsApp: message event error: {format_error(e)}")

    @client.event(KeepAliveTimeoutEv)
    async def on_keepalive_timeout(_client: NewAClient, _ev: KeepAliveTimeoutEv) -> None:
        nonlocal keepalive_failures
        keepalive_failures += 1
        PrintStyle.warning(
            f"WhatsApp: keepalive timeout ({keepalive_failures}/{MAX_KEEPALIVE_FAILURES})"
        )
        if keepalive_failures >= MAX_KEEPALIVE_FAILURES:
            connection_dead.set()

    @client.event(KeepAliveRestoredEv)
    async def on_keepalive_restored(_client: NewAClient, _ev: KeepAliveRestoredEv) -> None:
        nonlocal keepalive_failures
        if keepalive_failures > 0:
            PrintStyle.info("WhatsApp: keepalive restored")
            keepalive_failures = 0

    @client.qr
    async def on_qr(_client: NewAClient, qr_data: bytes) -> None:
        PrintStyle.info(f"WhatsApp: QR code received ({len(qr_data)} bytes)")
        await qr_callback(qr_data)

    await _check_connectivity()
    PrintStyle.info("WhatsApp: connecting...")
    await client.connect()
    PrintStyle.info("WhatsApp: connect() returned, waiting on idle()...")

    # Wait for either idle() to complete or connection death from keepalive timeouts
    idle_task = asyncio.create_task(client.idle())
    death_task = asyncio.create_task(connection_dead.wait())

    try:
        done, pending = await asyncio.wait(
            [idle_task, death_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    except asyncio.CancelledError:
        idle_task.cancel()
        death_task.cancel()
        raise

    if death_task in done:
        PrintStyle.warning("WhatsApp: connection dead after keepalive timeouts, reconnecting...")


async def disconnect_client(client: NewAClient) -> None:
    try:
        await client.disconnect()
    except Exception:
        pass


async def logout_client(client: NewAClient) -> None:
    try:
        await client.logout()
    except Exception:
        pass


# ------------------------------------------------------------------
# Sending
# ------------------------------------------------------------------

async def send_message(client: NewAClient, jid_str: str, text: str) -> None:
    if not text:
        return
    jid = _parse_jid(jid_str)
    await client.send_message(jid, text)


async def send_document(
    client: NewAClient,
    jid_str: str,
    content_bytes: bytes,
    filename: str,
) -> None:
    jid = _parse_jid(jid_str)
    await client.send_document(jid, content_bytes, filename=filename)


async def send_image(
    client: NewAClient,
    jid_str: str,
    content_bytes: bytes,
    caption: str = "",
) -> None:
    jid = _parse_jid(jid_str)
    await client.send_image(jid, content_bytes, caption=caption)


# ------------------------------------------------------------------
# Receiving / extraction
# ------------------------------------------------------------------

async def extract_message(
    client: NewAClient,
    msg_event: MessageEv,
) -> InboundMessage | None:
    info = msg_event.Info
    source = info.MessageSource
    msg = msg_event.Message

    chat_jid = Jid2String(source.Chat)
    sender_jid = Jid2String(source.Sender)
    sender_name = info.Pushname or sender_jid
    message_id = info.ID
    chat_type = "group" if source.IsGroup else "private"

    text = ""
    has_media = False

    # Text messages
    if msg.conversation:
        text = msg.conversation
    elif msg.extendedTextMessage.text:
        text = msg.extendedTextMessage.text

    # Image
    elif msg.imageMessage.url:
        text = msg.imageMessage.caption or "[Image]"
        has_media = True

    # Document
    elif msg.documentMessage.url:
        fname = msg.documentMessage.fileName or "document"
        text = msg.documentMessage.caption or f"[Document: {fname}]"
        has_media = True

    # Audio / Voice
    elif msg.audioMessage.url:
        if msg.audioMessage.ptt:
            text = "[Voice message]"
        else:
            text = "[Audio]"
        has_media = True

    # Video
    elif msg.videoMessage.url:
        text = msg.videoMessage.caption or "[Video]"
        has_media = True

    # Sticker
    elif msg.stickerMessage.url:
        text = "[Sticker]"
        has_media = True

    # Location
    elif msg.locationMessage.degreesLatitude or msg.locationMessage.degreesLongitude:
        lat = msg.locationMessage.degreesLatitude
        lon = msg.locationMessage.degreesLongitude
        text = f"Location: {lat} {lon}"

    # Contact
    elif msg.contactMessage.displayName:
        name = msg.contactMessage.displayName
        text = f"Contact: {name}"

    else:
        return None

    # Download media attachments
    attachments: list[str] = []
    if has_media:
        path = await download_media(client, msg)
        if path:
            attachments.append(path)

    # Command detection
    is_command = False
    command = ""
    if text.startswith("/"):
        is_command = True
        cmd = text.split()[0].lstrip("/").lower()
        if cmd in ("start", "reset"):
            command = cmd

    return InboundMessage(
        chat_jid=chat_jid,
        sender_jid=sender_jid,
        sender_name=sender_name,
        text=text,
        message_id=message_id,
        chat_type=chat_type,
        attachments=attachments,
        is_command=is_command,
        command=command,
        raw_event=msg_event,
    )


# ------------------------------------------------------------------
# Media download
# ------------------------------------------------------------------

async def download_media(client: NewAClient, message: Any) -> str | None:
    try:
        data = await client.download_any(message)
        if not data:
            return None

        content_b64 = base64.b64encode(data).decode()

        from helpers import guids, runtime
        from plugins._whatsapp_integration.helpers.attachment_writer import write_attachment

        unique = guids.generate_id()
        ext = _guess_media_ext(message)
        rel_path = f"{DOWNLOAD_FOLDER}/{unique}{ext}"

        result = await runtime.call_development_function(
            write_attachment, rel_path, content_b64,
        )
        if result["error"]:
            return None
        return result["path"]
    except Exception:
        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_jid(jid_str: str) -> Any:
    from neonize.utils.jid import build_jid
    parts = jid_str.split("@")
    if len(parts) == 2:
        user, server = parts
        return build_jid(user, server)
    return build_jid(jid_str)


async def _check_connectivity() -> None:
    """Check WhatsApp server reachability before connecting (prevents Go panic)."""
    import asyncio
    import socket

    loop = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _tcp_check, "web.whatsapp.com", 443),
            timeout=15,
        )
    except (asyncio.TimeoutError, OSError) as e:
        raise ConnectionError(
            f"Cannot reach WhatsApp servers (web.whatsapp.com:443): {e}"
        ) from e


def _tcp_check(host: str, port: int) -> None:
    from socket import create_connection
    sock = create_connection((host, port), timeout=10)
    sock.close()


def _guess_media_ext(message: Any) -> str:
    if message.imageMessage.url:
        mime = message.imageMessage.mimetype
        if "png" in mime:
            return ".png"
        return ".jpg"
    if message.documentMessage.url:
        fname = message.documentMessage.fileName or ""
        _, ext = os.path.splitext(fname)
        return ext or ".bin"
    if message.audioMessage.url:
        if message.audioMessage.ptt:
            return ".ogg"
        return ".mp3"
    if message.videoMessage.url:
        return ".mp4"
    if message.stickerMessage.url:
        return ".webp"
    return ".bin"
