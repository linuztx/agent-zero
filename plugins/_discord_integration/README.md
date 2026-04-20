# Discord Integration

Communicate with Agent Zero via Discord. Each configured bot connects to the Discord Gateway over a persistent WebSocket, delivers messages in real time, and routes each user to a dedicated `AgentContext`.

## What It Does

- Run one or more Discord bots from Agent Zero. Each has its own token, access list, server mode, and project binding.
- DMs, guild text channels, forum posts, and threads are all supported. Each thread/channel/user tuple becomes its own persistent chat.
- Inbound attachments are downloaded to `usr/uploads/` and passed to the agent. Outbound attachments from the `response` tool are uploaded via `discord.File`.
- The agent can attach a `keyboard` array to the `response` tool — it renders as Discord buttons; clicks feed back as `[Button pressed: <custom_id>]` user messages.
- Shared `/project`, `/config`, `/send`, `/queue` commands work as text-prefix messages (not Discord slash commands).

## Requirements

- Python environment with `uv` available (the plugin installs `discord.py` via `uv pip install` on first use).
- A Discord application with a bot user. Message Content intent must be enabled in the Developer Portal for the bot to see message text.

## Setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications), create an application, open the **Bot** tab.
2. Reset the bot token and copy it.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent**. Enable **Server Members Intent** if you plan to use welcome messages.
4. In Agent Zero: Settings → External → Discord Integration → **Connect a bot**. Paste the token and click **Check Discord connection**. The Application ID auto-populates so the invite URL builder can produce a working link.
5. Copy the invite URL, open it in a browser, and add the bot to one of your servers.
6. Add at least one Discord user ID or guild ID to the access lists (leaving both empty makes the bot open to everyone in every shared server).
7. Toggle **Turn on this bot** and save the settings.

The bot joins the gateway on the next Agent Zero job-loop tick. Logs will show `Discord (<name>): ready as <tag>` when it is live.

## Configuration

| Setting | Description | Default |
| --- | --- | --- |
| `enabled` | Connect to the gateway and respond to messages | `false` |
| `token` | Bot token from the Developer Portal | `""` |
| `client_id` | Application ID; used to build the invite URL | auto-filled after test |
| `allowed_users` | Discord user IDs allowed to talk to the bot | `[]` (open) |
| `allowed_guilds` | Discord guild IDs where the bot will respond | `[]` (any) |
| `server_mode` | `mention` \| `all` \| `off` (DMs only) | `mention` |
| `welcome_enabled` | Send a greeting on member join (needs Server Members intent) | `false` |
| `welcome_message` | Greeting template (`{name}` is substituted) | `Welcome, {name}!` |
| `default_project` | Fallback Agent Zero project for conversations from this bot | `""` |
| `user_projects` | Per-user project mapping, e.g. `{ "12345": "support" }` | `{}` |
| `agent_instructions` | Extra system prompt for Discord chats | `""` |
| `attachment_max_age_hours` | Auto-delete downloaded files after N hours (0 = never) | `0` |
| `notify_messages` | Surface a WebUI notification per inbound message | `false` |

## How It Works

```
Discord Gateway (WebSocket)
    ↕
discord.Client subclass (per bot, asyncio.Task)
    ↕ (on_message / on_interaction / on_member_join)
helpers/handler.py  →  AgentContext.communicate(UserMessage(...))
    ↕ (extensions)
Agent Zero
    ↕ (response tool → process_chain_end)
helpers/handler.py::send_discord_reply  →  channel.send
```

- `extensions/python/job_loop/_10_discord_bot.py` reconciles enabled bots every tick and starts/stops them.
- `extensions/python/system_prompt/_20_discord_context.py` injects `fw.discord.system_context_reply.md` when a session has `CTX_DC_BOT`.
- `extensions/python/tool_execute_after/_50_discord_response.py` captures attachments/keyboard from the `response` tool and sends mid-run updates when `break_loop=false`.
- `extensions/python/process_chain_end/_55_discord_reply.py` sends the final agent response, retrying up to twice on failure.

## State & Persistence

- Per-chat mapping lives in `usr/plugins/_discord_integration/state.json` keyed by `"{bot}:{user_id}:{channel_id}"`. Contexts survive restarts; `/clear` resets just one chat.
- Downloaded attachments are stored under `usr/uploads/dc_<bot>_<uuid>_<name>`.
- Session persistence on the Discord side is not needed — each restart re-logs into the gateway from the token.

## Gotchas

- Messages over 2000 characters are split automatically.
- Files larger than the 25 MB bot upload limit are skipped with a warning.
- The typing indicator is refreshed every 8 seconds while the agent works, capped at 10 minutes to avoid leaking threads.
- Discord bots cannot DM a user they don't share a guild with — have the user message the bot first.
- Disabling a bot in the settings closes its gateway connection on the next job-loop tick.
