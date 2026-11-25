"""MCP server instructions as the agent system prompt carries them.

An MCP server may return an ``instructions`` string from ``initialize`` that
says how its tools are meant to be used. The specification offers it as a
hint clients may add to the system prompt. The text is the server's, so it is
held inside its own subsection before it joins the prompt: it is cut to a
bounded size with an explicit marker, every Markdown heading in it is pushed
below the section's own headings, and a code fence left open is closed. One
server's text therefore cannot open a prompt section of its own or pose as
another server's part.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any, Callable, Iterable

SECTION_TEMPLATE = "agent.system.mcp_instructions.md"
SERVER_TEMPLATE = "agent.system.mcp_server_instructions.md"

# Room for real usage notes; a server pasting its whole manual cannot spend
# the context window on it.
MAX_SERVER_INSTRUCTIONS_CHARS = 4096
TRUNCATION_MARKER = "...[truncated]"

# The section renders under a level-2 heading and each server under a level-3
# heading, so headings in server text are pushed to level 4 or deeper.
HEADING_SHIFT = 3
MAX_HEADING_LEVEL = 6

_LINE_SEPARATORS = str.maketrans({"\r": "\n", " ": "\n", " ": "\n"})
_HEADING = re.compile(r"^( {0,3})(#{1,6})(?=[ \t]|$)")
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")


def normalize_instructions(value: Any) -> str:
    """Return trimmed instruction text with plain newlines, or "" for none.

    Non-string values count as no instructions. Control characters other than
    newline and tab are dropped.
    """
    if not isinstance(value, str):
        return ""
    text = value.replace("\r\n", "\n").translate(_LINE_SEPARATORS)
    text = "".join(
        char
        for char in text
        if char in "\n\t" or unicodedata.category(char) != "Cc"
    )
    return text.strip()


def contain_instructions(
    text: Any, max_chars: int = MAX_SERVER_INSTRUCTIONS_CHARS
) -> str:
    """Hold one server's instructions inside its prompt subsection.

    Headings are pushed down inside code fences too: whatever reads the prompt
    reads it line by line, while a ``#`` comment stays a comment.
    """
    body = normalize_instructions(text)
    if not body:
        return ""
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n" + TRUNCATION_MARKER

    lines: list[str] = []
    open_fence = ""
    for line in body.split("\n"):
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if not open_fence:
                open_fence = marker
            elif line.strip() == marker and marker[0] == open_fence[0] and len(
                marker
            ) >= len(open_fence):
                open_fence = ""
        lines.append(_demote_heading(line))
    if open_fence:
        lines.append(open_fence)
    return "\n".join(lines)


def render_literal(render: Callable[..., str], file: str, **values: Any) -> str:
    """Render a prompt template and insert ``values`` verbatim afterwards.

    Prompt rendering expands includes and placeholders inside substituted
    values, so server-supplied text is swapped in only after the template
    itself has been rendered.
    """
    tokens = {key: f"@@a0-literal-{key}-{uuid.uuid4().hex}@@" for key in values}
    rendered = render(file, **tokens)
    for key, token in tokens.items():
        rendered = rendered.replace(token, str(values[key]))
    return rendered


def build_instructions_section(
    servers: Iterable[tuple[str, Any]], render: Callable[..., str]
) -> str:
    """Render the prompt section for ``(server_name, instructions)`` pairs.

    Pairs keep their given order and servers with blank instructions are
    skipped. With nothing to say the section is empty, so the prompt does not
    change.
    """
    parts: list[str] = []
    for name, text in servers:
        body = contain_instructions(text)
        if not body:
            continue
        parts.append(
            render_literal(
                render,
                SERVER_TEMPLATE,
                server_name=_one_line(name),
                instructions=body,
            ).strip()
        )
    if not parts:
        return ""
    return render_literal(
        render, SECTION_TEMPLATE, servers="\n\n".join(parts)
    ).strip()


def _demote_heading(line: str) -> str:
    match = _HEADING.match(line)
    if not match:
        return line
    level = min(len(match.group(2)) + HEADING_SHIFT, MAX_HEADING_LEVEL)
    return f"{match.group(1)}{'#' * level}{line[match.end():]}"


def _one_line(name: Any) -> str:
    text = "".join(
        " " if unicodedata.category(char) in {"Cc", "Zl", "Zp"} else char
        for char in str(name or "")
    )
    return " ".join(text.replace("`", "'").split())
