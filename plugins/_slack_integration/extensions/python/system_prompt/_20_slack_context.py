"""Inject Slack conversation context into the system prompt for Slack sessions."""

from agent import LoopData
from helpers import plugins
from helpers.extension import Extension

from plugins._slack_integration.helpers.routing import (
    CTX_SLACK_CHANNEL_ID,
    CTX_SLACK_WORKSPACE,
    PLUGIN_NAME,
)


class SlackContextPrompt(Extension):

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs,
    ):
        if not self.agent:
            return

        context = self.agent.context
        if not context.data.get(CTX_SLACK_CHANNEL_ID):
            return

        system_prompt.append(
            self.agent.read_prompt("fw.slack.system_context_reply.md")
        )

        handler_name = context.data.get(CTX_SLACK_WORKSPACE, "")
        if not handler_name:
            return

        config = plugins.get_plugin_config(PLUGIN_NAME) or {}
        for h in config.get("handlers", []):
            if h.get("name") == handler_name:
                instructions = (h.get("agent_instructions") or "").strip()
                if instructions:
                    system_prompt.append(
                        self.agent.read_prompt(
                            "fw.slack.user_message_instructions.md",
                            instructions=instructions,
                        )
                    )
                break
