# Slack Integration Plugin

Communicate with Agent Zero via Slack. Uses Slack Socket Mode so no public
webhook URL is needed — a WebSocket connection from your Agent Zero instance
to Slack handles events and replies.

## Requirements

- A Slack workspace where you can install apps
- `slack_sdk>=3.27.0` (auto-installed by the plugin installer)

## Setup

### 1. Create a Slack app

1. Go to <https://api.slack.com/apps> and click **Create New App**
2. Choose **From an app manifest**, pick your workspace, then paste the
   manifest below. Adjust the bot name and description as needed.

```yaml
display_information:
  name: Agent Zero
  description: AI assistant powered by Agent Zero
features:
  bot_user:
    display_name: Agent Zero
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - chat:write
      - files:read
      - files:write
      - groups:history
      - im:history
      - im:read
      - im:write
      - mpim:history
      - reactions:read
      - reactions:write
      - users:read
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.channels
      - message.groups
      - message.im
      - message.mpim
  interactivity:
    is_enabled: true
  socket_mode_enabled: true
```

3. Install the app to your workspace. Copy the **Bot User OAuth Token**
   (`xoxb-...`) from *OAuth & Permissions*.
4. Create an **App-Level Token** under *Basic Information → App-Level Tokens*
   with the `connections:write` scope. Copy the token (`xapp-...`).

### 2. Configure Agent Zero

1. Enable the plugin in *Settings → External → Slack Integration*.
2. Add a handler and paste the two tokens.
3. Optionally restrict `allowed_channels` / `allowed_users`, pick a project,
   and click **Check connection** to verify `auth.test`, the Socket Mode
   handshake, and required scopes.
4. Invite the bot to any channels you want it to listen in.

### 3. Talk to the bot

- **DMs** — one conversation per person.
- **Channel mention** — `@Agent Zero help me with X` starts a new thread.
  All follow-ups in that thread route to the same Agent Zero context.
- **Existing threads** — replying to any of the bot's earlier messages in a
  thread continues that conversation.

### 4. Control commands

Send plain text (not slash commands) inside the chat to control the active
conversation:

| Command | Effect |
|---------|--------|
| `/project <name>` | Switch the active project for this chat |
| `/project none` | Clear the active project |
| `/config <preset>` | Switch to a model preset |
| `/config default` | Use the default model config |
| `/send` | Flush any queued messages as a batch |

## Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| `name` | Unique handler slug (used as listener key) | required |
| `enabled` | Enable Socket Mode listener for this handler | `false` |
| `bot_token` | Bot User OAuth Token (`xoxb-...`) | required |
| `app_token` | App-Level Token with `connections:write` (`xapp-...`) | required |
| `listen_dm` | Respond to direct messages | `true` |
| `listen_channels` | Respond to channel messages and `app_mention` | `true` |
| `allowed_channels` | Channel IDs allow list (empty = all) | `[]` |
| `allowed_users` | User IDs allow list (empty = all) | `[]` |
| `denied_users` | User IDs deny list | `[]` |
| `use_thinking_reaction` | Add `:thinking_face:` while processing | `true` |
| `thinking_emoji` | Emoji name for the thinking reaction | `"thinking_face"` |
| `project` | Activate project for new Slack chats | `""` |
| `chat_model_preset` | Model preset for new Slack chats | `""` |
| `agent_instructions` | Extra agent instructions for Slack sessions | `""` |
| `max_upload_size_mb` | Skip outbound uploads larger than this | `25` |

## How it works

1. A Socket Mode WebSocket connection per enabled handler receives events.
2. Incoming `message` and `app_mention` events are filtered (self, allow
   list) and deduplicated, then dispatched to a Python handler.
3. Each message routes to an `AgentContext` keyed by
   `(channel_id, thread_ts)` — DMs use channel alone so one conversation
   equals one context per peer.
4. Agent replies are sent via `chat.postMessage` in the same thread, with
   markdown converted to Slack `mrkdwn`.
5. Inbound files are downloaded via the bot token and written into the
   execution runtime; outbound files use `files_upload_v2`.

## Architecture

```
Slack workspace
    ↕ (Events API over Socket Mode WebSocket)
slack_sdk SocketModeClient (per handler)
    ↕
Python helpers (slack_client, handler, routing, socket_listener)
    ↕ (framework extensions)
Agent Zero
```
