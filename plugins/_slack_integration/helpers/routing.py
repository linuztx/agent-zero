"""Route inbound Slack events to AgentContext instances.

Routing key depends on channel type:
  - DMs (`im`): (workspace, channel_id) — one context per DM peer
  - Channels/groups: (workspace, channel_id, thread_ts)

`find_context` walks AgentContext._contexts matching these keys. Creation
lives in handler.py because it needs plugin-specific side effects (save
tmp chat, project activation, initial user message).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent import AgentContext


PLUGIN_NAME = "_slack_integration"

CTX_SLACK_WORKSPACE = "slack_workspace"
CTX_SLACK_TEAM_ID = "slack_team_id"
CTX_SLACK_CHANNEL_ID = "slack_channel_id"
CTX_SLACK_CHANNEL_TYPE = "slack_channel_type"
CTX_SLACK_THREAD_TS = "slack_thread_ts"
CTX_SLACK_USER_ID = "slack_user_id"
CTX_SLACK_USER_NAME = "slack_user_name"
CTX_SLACK_LAST_TS = "slack_last_ts"

# Transient — consumed per-reply, not persisted
CTX_SLACK_ATTACHMENTS = "_slack_response_attachments"
CTX_SLACK_REPLY_IN_THREAD = "_slack_reply_in_thread"
CTX_SLACK_THINKING_ACTIVE = "_slack_thinking_reaction_active"
CTX_SLACK_THINKING_TS = "_slack_thinking_reaction_ts"


def find_context(
    workspace: str, channel_id: str, thread_ts: str, channel_type: str,
) -> str | None:
    """Return the most recent matching AgentContext id, or None.

    For DMs, `thread_ts` is ignored — one context per channel.
    """
    from agent import AgentContext

    is_dm = channel_type == "im"
    matches: list[str] = []
    for ctx_id, ctx in AgentContext._contexts.items():
        if not isinstance(ctx, AgentContext):
            continue
        data = ctx.data
        if data.get(CTX_SLACK_WORKSPACE) != workspace:
            continue
        if data.get(CTX_SLACK_CHANNEL_ID) != channel_id:
            continue
        if not is_dm:
            if (data.get(CTX_SLACK_THREAD_TS) or "") != (thread_ts or ""):
                continue
        matches.append(ctx_id)

    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0]
