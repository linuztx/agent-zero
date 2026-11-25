# mcp_instructions.py DOX

## Purpose

- Own the `mcp_instructions.py` helper module.
- This module turns the optional `instructions` that MCP servers return from `initialize` into a bounded, contained system-prompt section.
- Keep this file-level DOX profile synchronized with `mcp_instructions.py` because this directory is intentionally flat.

## Ownership

- `mcp_instructions.py` owns the runtime implementation.
- `mcp_instructions.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Top-level functions:
- `normalize_instructions(value: Any) -> str`: Trim instruction text, turn CRLF, CR and Unicode line/paragraph separators into newlines, and drop control characters other than newline and tab. Non-string values become `""`.
- `contain_instructions(text: Any, max_chars: int = MAX_SERVER_INSTRUCTIONS_CHARS) -> str`: Hold one server's text inside its prompt subsection.
- `render_literal(render: Callable[..., str], file: str, **values: Any) -> str`: Render a prompt template, then insert `values` verbatim.
- `build_instructions_section(servers: Iterable[tuple[str, Any]], render: Callable[..., str]) -> str`: Render the whole section for `(server_name, instructions)` pairs.
- Notable constants/configuration names: `SECTION_TEMPLATE`, `SERVER_TEMPLATE`, `MAX_SERVER_INSTRUCTIONS_CHARS`, `TRUNCATION_MARKER`, `HEADING_SHIFT`, `MAX_HEADING_LEVEL`.

## Runtime Contracts

- The module is pure: no I/O, settings, network, or agent state. `helpers/mcp_handler.py` supplies the policy-filtered server pairs and a prompt renderer.
- Containment cuts text past 4096 characters and appends an explicit `...[truncated]` line. It pushes every ATX heading (up to three leading spaces) three levels down, capped at level 6, including inside code fences, and closes a fence left open. Server text therefore cannot start a level 1-3 heading, so it cannot open a prompt section or pose as another server's `###` part.
- Prompt rendering expands includes and placeholders inside substituted values. `render_literal` therefore renders templates with random sentinel tokens and swaps the server-supplied text in afterwards. Server text is never passed to the template engine.
- Server names are reduced to one line, and backticks become apostrophes because the server template quotes the name.
- Pairs keep their given order. Blank instructions are skipped, and no pairs with text yields `""` so the system prompt is unchanged.
- `prompts/agent.system.mcp_instructions.md` owns the section heading and framing. `prompts/agent.system.mcp_server_instructions.md` owns each server's heading.
- Update this file whenever public functions, containment rules, size bounds, or template names change.
- Imported dependency areas include: `re`, `typing`, `unicodedata`, `uuid`.

## Key Concepts

- MCP servers' instructions are server-chosen text. The framing presents them as context for that server's tools, never as capabilities or overrides.
- Byte-stable output (no timestamps or status) keeps the system prompt and provider prompt caches stable across turns.

## Work Guidance

- Keep the module dependency-free so containment stays testable without MCP transports.
- Change the heading shift together with the templates' heading levels.

## Verification

- Run `pytest tests/test_mcp_server_instructions.py`.

## Child DOX Index

No child DOX files.
