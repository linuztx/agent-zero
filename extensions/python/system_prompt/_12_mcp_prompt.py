from typing import Any

from helpers import responses_tools, settings
from helpers.extension import Extension, extensible
from helpers.mcp_handler import MCPConfig
from agent import Agent, LoopData


class MCPToolsPrompt(Extension):

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent:
            return
        prompt = await build_prompt(self.agent)
        if prompt:
            system_prompt.append(prompt)
            responses_tools.register_prompt(self.agent, loop_data, "mcp", prompt)
            # A separate element: the Responses projection replaces only the
            # registered tools text, so instructions reach both transports.
            instructions = await build_instructions_prompt(self.agent)
            if instructions:
                system_prompt.append(instructions)


@extensible
async def build_prompt(agent: Agent) -> str:
    mcp_config = MCPConfig.get_for_agent(agent)
    if not mcp_config.servers:
        return ""

    pre_progress = agent.context.log.progress
    agent.context.log.set_progress("Collecting MCP tools")
    tools = mcp_config.get_tools_prompt(agent=agent)
    agent.context.log.set_progress(pre_progress)
    return tools


@extensible
async def build_instructions_prompt(agent: Agent) -> str:
    if not settings.get_settings_for_prompt().get("mcp_client_instructions_enabled", True):
        return ""
    mcp_config = MCPConfig.get_for_agent(agent)
    if not mcp_config.servers:
        return ""
    return mcp_config.get_instructions_prompt(agent=agent)
