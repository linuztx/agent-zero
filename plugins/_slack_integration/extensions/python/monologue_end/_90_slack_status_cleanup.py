"""Remove the :thinking_face: reaction after the agent's monologue finishes."""

from helpers.extension import Extension

from plugins._slack_integration.helpers.routing import (
    CTX_SLACK_CHANNEL_ID,
    CTX_SLACK_THINKING_ACTIVE,
)


class SlackStatusCleanup(Extension):

    async def execute(self, **kwargs):
        if not self.agent:
            return
        context = self.agent.context
        if not context.data.get(CTX_SLACK_CHANNEL_ID):
            return
        if not context.data.get(CTX_SLACK_THINKING_ACTIVE):
            return

        from plugins._slack_integration.helpers.handler import _remove_thinking_reaction
        await _remove_thinking_reaction(context)
