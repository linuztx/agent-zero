"""Inject Discord session behavior into the system prompt."""

from agent import LoopData
from helpers.extension import Extension
from plugins._discord_integration.helpers.constants import (
    CTX_DC_BOT,
    CTX_DC_BOT_CFG,
)


class DiscordContextPrompt(Extension):

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs,
    ):
        if not self.agent:
            return

        if not self.agent.context.data.get(CTX_DC_BOT):
            return

        system_prompt.append(
            self.agent.read_prompt("fw.discord.system_context_reply.md")
        )

        bot_cfg = self.agent.context.data.get(CTX_DC_BOT_CFG, {})
        instructions = (bot_cfg or {}).get("agent_instructions", "")
        if instructions:
            system_prompt.append(
                self.agent.read_prompt(
                    "fw.discord.user_message_instructions.md",
                    instructions=instructions,
                )
            )
