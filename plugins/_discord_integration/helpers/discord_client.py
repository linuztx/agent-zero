"""
Discord client helpers — thin wrappers around discord.py primitives.

No agent/tool dependencies. Imports discord lazily so callers that only want
pure-Python utilities (_split_text, md_for_discord) don't pay the cost.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from helpers.errors import format_error
from helpers.print_style import PrintStyle

from plugins._discord_integration.helpers.constants import (
    MAX_ATTACHMENT_BYTES,
    MAX_MESSAGE_LENGTH,
)

if TYPE_CHECKING:
    import discord


_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def is_image_file(path: str) -> bool:
    _, ext = os.path.splitext(path.lower())
    return ext in _IMAGE_EXTENSIONS


# ------------------------------------------------------------------
# Text splitting
# ------------------------------------------------------------------

def _split_text(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a string into chunks <= max_len, preferring newline boundaries."""
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


# ------------------------------------------------------------------
# Markdown cleanup — Discord speaks native Markdown, so this is minimal.
# ------------------------------------------------------------------

_TABLE_RE = re.compile(r"^\|(.+)\|$")
_TABLE_SEP = re.compile(r"^[\s|:-]+$")


def _strip_tables(text: str) -> str:
    """Flatten Markdown tables into plain lines — Discord does not render them."""
    out: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if _TABLE_SEP.match(stripped):
            continue
        m = _TABLE_RE.match(stripped)
        if m:
            out.append("  ".join(c.strip() for c in m.group(1).split("|")))
        else:
            out.append(line)
    return "\n".join(out)


def md_for_discord(text: str) -> str:
    """Clean agent output for Discord: strip leaked HTML tags and Markdown tables.

    Discord renders native Markdown (bold, italic, strikethrough, lists, fences,
    inline code, blockquotes, links) directly, so no conversion is needed beyond
    removing syntax that wouldn't render.
    """
    if not text:
        return ""

    # Protect fenced code blocks and inline code from HTML tag stripping
    stash: list[str] = []

    def _save(match: re.Match) -> str:
        stash.append(match.group(0))
        return f"\x00C{len(stash) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```", _save, text)
    text = re.sub(r"`[^`\n]+`", _save, text)

    # Strip stray HTML tags (e.g. agent output bled through from a web tool)
    text = re.sub(r"<[^>]+>", "", text)

    # Flatten tables
    text = _strip_tables(text)

    # Restore code blocks
    for i, block in enumerate(stash):
        text = text.replace(f"\x00C{i}\x00", block)

    return text


# ------------------------------------------------------------------
# Sending helpers
# ------------------------------------------------------------------

async def send_text(
    channel: "discord.abc.Messageable",
    text: str,
    reply_to: "discord.Message | None" = None,
    view: "discord.ui.View | None" = None,
) -> "discord.Message | None":
    """Send (possibly split) text. View is attached to the last chunk only."""
    if not text:
        return None

    chunks = _split_text(text)
    last_msg = None
    last_idx = len(chunks) - 1
    for idx, chunk in enumerate(chunks):
        kwargs: dict[str, Any] = {"content": chunk}
        if idx == 0 and reply_to is not None:
            kwargs["reference"] = reply_to
            kwargs["mention_author"] = False
        if idx == last_idx and view is not None:
            kwargs["view"] = view
        try:
            last_msg = await channel.send(**kwargs)
        except Exception as e:
            PrintStyle.error(f"Discord send_text failed: {format_error(e)}")
            return last_msg
    return last_msg


async def send_file(
    channel: "discord.abc.Messageable",
    path: str,
    caption: str = "",
    reply_to: "discord.Message | None" = None,
) -> "discord.Message | None":
    """Send a local file as a Discord attachment. Rejects files over the size cap."""
    import discord

    if not os.path.isfile(path):
        PrintStyle.error(f"Discord: file not found: {path}")
        return None

    size = os.path.getsize(path)
    if size > MAX_ATTACHMENT_BYTES:
        PrintStyle.warning(
            f"Discord: file '{os.path.basename(path)}' is {size} bytes, "
            f"exceeds {MAX_ATTACHMENT_BYTES} byte upload limit; skipping"
        )
        return None

    try:
        kwargs: dict[str, Any] = {
            "file": discord.File(path),
        }
        if caption:
            kwargs["content"] = caption[:MAX_MESSAGE_LENGTH]
        if reply_to is not None:
            kwargs["reference"] = reply_to
            kwargs["mention_author"] = False
        return await channel.send(**kwargs)
    except Exception as e:
        PrintStyle.error(f"Discord send_file failed: {format_error(e)}")
        return None


async def send_typing_once(client: "discord.Client", channel_id: int) -> None:
    """Trigger the typing indicator for ~10 seconds via the low-level HTTP client."""
    try:
        await client.http.send_typing(channel_id)
    except Exception:
        pass


# ------------------------------------------------------------------
# Interactive button views
# ------------------------------------------------------------------

def build_button_view(keyboard: list[list[dict]]) -> "discord.ui.View | None":
    """Build a View from a [[{text, callback_data|url}]] keyboard spec.

    Respects Discord's limits: 5 rows, 5 buttons per row.
    """
    import discord

    if not keyboard:
        return None

    view = discord.ui.View(timeout=None)
    for row_idx, row in enumerate(keyboard[:5]):
        for btn in row[:5]:
            label = str(btn.get("text", "")).strip() or "Button"
            if "url" in btn and btn["url"]:
                view.add_item(
                    discord.ui.Button(
                        label=label[:80],
                        url=str(btn["url"]),
                        style=discord.ButtonStyle.link,
                        row=row_idx,
                    )
                )
            else:
                custom_id = str(btn.get("callback_data", label))[:100]
                view.add_item(
                    discord.ui.Button(
                        label=label[:80],
                        custom_id=custom_id,
                        style=discord.ButtonStyle.secondary,
                        row=row_idx,
                    )
                )
    return view
