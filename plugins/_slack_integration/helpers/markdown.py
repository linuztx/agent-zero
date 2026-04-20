"""Markdown → Slack mrkdwn conversion."""

import re


def md_to_slack(text: str) -> str:
    """Convert standard Markdown to Slack mrkdwn.

    Slack mrkdwn differs from Markdown:
      - bold uses single `*` (not `**`)
      - italic uses `_` (same)
      - strikethrough uses `~` (not `~~`)
      - links use `<url|label>` (not `[label](url)`)
      - headings are not supported — render as bold
    """
    if not text:
        return ""

    code_blocks: list[str] = []

    def _save_code(m: re.Match) -> str:
        code_blocks.append(m.group(0))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```", _save_code, text)

    inline_codes: list[str] = []

    def _save_inline(m: re.Match) -> str:
        inline_codes.append(m.group(0))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r"`[^`]+`", _save_inline, text)

    # Bold+italic ***text*** → *_text_*
    text = re.sub(r"\*{3}(.+?)\*{3}", r"*_\1_*", text)
    # Bold **text** or __text__ → *text*
    text = re.sub(r"\*{2}(.+?)\*{2}", r"*\1*", text)
    text = re.sub(r"__(.+?)__", r"*\1*", text)
    # Italic _text_ stays _text_ (same in Slack)
    # Strikethrough ~~text~~ → ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    # Headings → bold
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    # Markdown links [label](url) → <url|label>
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", text)

    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CB{i}\x00", block)
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00IC{i}\x00", code)

    return text
