"""Download a Slack file via its url_private using the bot token."""

import aiohttp


async def download_private_file(
    url: str, bot_token: str, max_bytes: int | None = None,
) -> tuple[bytes, str]:
    """Fetch a Slack private file. Returns (content_bytes, error_str)."""
    headers = {"Authorization": f"Bearer {bot_token}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return b"", f"http {resp.status}"
                content = await resp.read()
                if max_bytes is not None and len(content) > max_bytes:
                    return b"", f"file too large ({len(content)} bytes)"
                return content, ""
    except Exception as e:
        return b"", str(e)
