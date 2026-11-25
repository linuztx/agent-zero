# Advanced MCP Configuration

Most users should start with [MCP Setup](../guides/mcp-setup.md).

This page is for people who need to paste or review MCP JSON by hand. MCP
architecture and source-linked internals live in
[DeepWiki for Agent Zero](https://deepwiki.com/agent0ai/agent-zero).

## Basic Shape

Command-based MCP tool:

```json
{
  "mcpServers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "/root/db.sqlite"]
    }
  }
}
```

URL-based MCP tool:

```json
{
  "mcpServers": {
    "external-api": {
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

## Common Fields

| Field | Meaning |
| --- | --- |
| `command` | Starts a local MCP tool from a command. |
| `args` | Arguments passed to that command. |
| `url` | Connects to an MCP tool that is already running. |
| `headers` | Optional HTTP headers, often used for authentication. |
| `env` | Optional environment variables for command-based tools. |
| `disabled` | Temporarily turns one MCP entry off. |

Use `command` for local tools and `url` for tools that are already running
somewhere else.

## Server Instructions

MCP servers may return an `instructions` string when Agent Zero initializes
them. Agent Zero captures it each time it lists the server's tools. It then
appends the instructions to the system prompt after the MCP tools section:

```text
## MCP server instructions
<framing>

### Instructions from MCP server `docs`
<the server's text>
```

- A server contributes only while the active profile's tool policy allows at
  least one of its enabled tools.
- Each server's text is cut at 4,096 characters with an explicit
  `...[truncated]` marker.
- Its Markdown headings are pushed below the section's own headings, and an
  unclosed code fence is closed. One server's text cannot pose as a new section
  or as another server.
- The text appears in Chat Completions and Responses API turns alike, and the
  context-window indicator counts it under MCP tools.
- The server status API reports `has_instructions`. The server detail API
  returns the captured `instructions` text.

The `mcp_client_instructions_enabled` setting (default `true`) controls the
section. It is **Use server instructions** in the External MCP Servers settings,
or `A0_SET_mcp_client_instructions_enabled=false` in the environment.

## Docker Addresses

If Agent Zero runs in Docker, remember that "localhost" means the container, not
always your host machine.

| Where the MCP tool runs | Address to use from Agent Zero |
| --- | --- |
| Host machine on macOS or Windows | `host.docker.internal` |
| Another container | The container name on the same Docker network |
| Remote machine | Its reachable HTTPS URL |
| Inside Agent Zero's container | A command-based config |

On Linux, `host.docker.internal` may need extra Docker setup. Running the MCP
tool in the same Docker network is often simpler.

## Safety

- Use MCP tools you trust.
- Server instructions are third-party text added to the agent's system prompt.
  Review them in the server's tools view, scan new servers, or turn off **Use
  server instructions** for servers you do not fully trust.
- Keep real API keys out of public screenshots and repositories.
- Prefer project secrets or environment variables for credentials.
- Remove MCP tools you no longer use.

## Related

- [MCP Setup](../guides/mcp-setup.md)
- [Browser Guide](../guides/browser.md)
- [A0 CLI Connector](../guides/a0-cli-connector.md)
- [DeepWiki for Agent Zero](https://deepwiki.com/agent0ai/agent-zero)
