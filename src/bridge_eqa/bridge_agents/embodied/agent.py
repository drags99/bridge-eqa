from bridge_eqa.bridge_agents.base_inspection_agent import InspectionAgent
from agents import Agent, Tool, ModelSettings
from bridge_eqa.bridge_agents.qa_response import (
    InspectionQuestionAnswerResponse,
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from typing import Coroutine, Any
import logfire
from agents import Runner, RunResult
from bridge_eqa.bridge_agents.agent_prompts import (
    DEFAULT_INSPECTION_GUIDELINES_PROMPT,
    ORACLE_TOOL_GUIDANCE,
    SCENE_GRAPH_TOOL_GUIDANCE,
    EMBODIED_FORMATTING_AGENT_PROMPT,
    EMBODIED_THINK_AGENT_PROMPT,
)


class EmbodiedInspectionAgent(InspectionAgent):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.agent_name = "Embodied Inspection Agent"
        self.tools: list[Tool] = kwargs.get("tools", [])
        self.agent = self._create_react_agent()

    def _create_react_agent(self):
        # Build base instructions with tool-specific guidance
        base_instructions = self._build_embodied_instructions()
        model_settings = ModelSettings(temperature=0)

        self.reformatting_agent = Agent(
            name="Formatting Agent",
            instructions=RECOMMENDED_PROMPT_PREFIX + EMBODIED_FORMATTING_AGENT_PROMPT,
            model=self.model_name,
            output_type=InspectionQuestionAnswerResponse,
            model_settings=model_settings,
        )

        self.think_agent = Agent(
            name="Embodied Inspection Agent",
            instructions=base_instructions + "\n\n" + EMBODIED_THINK_AGENT_PROMPT,
            model=self.model_name,
            tools=self.tools,
            model_settings=model_settings,
        )

        return self.think_agent

    def _build_embodied_instructions(self) -> str:
        """Build instructions with tool-specific guidance for Embodied agents."""
        instructions = DEFAULT_INSPECTION_GUIDELINES_PROMPT

        # Check if oracle tool is available
        has_oracle = any(
            tool.name == "oracle_tool" if isinstance(tool, Tool) else False
            for tool in self.tools
        )

        # Check if scene_graph_interface_tool is available
        has_scene_graph = any(
            tool.name == "scene_graph_interface_tool" if isinstance(tool, Tool) else False
            for tool in self.tools
        )

        # Add tool-specific guidance
        if has_oracle:
            instructions += "\n\n" + ORACLE_TOOL_GUIDANCE

        if has_scene_graph:
            instructions += "\n\n" + SCENE_GRAPH_TOOL_GUIDANCE

        return instructions

    def async_inspect(self, messages: list) -> Coroutine[Any,Any,RunResult]:
        message_ref = messages
        async def react_inspect():
            assert self.context is not None
            with logfire.span("Embodied Inspection Agent"):
                messages = message_ref
                # convert RunResponse to list if it is not already
                if isinstance(messages, RunResult):
                    messages = messages.to_input_list()
                messages = await Runner.run(
                    self.think_agent, messages, context=self.context, max_turns=20
                )
                # try to convert final output to correct output type if it fails 
                # messages_list = messages.to_input_list()
                message_output = messages.final_output
                if isinstance(message_output, InspectionQuestionAnswerResponse):
                    return messages
                else:
                    messages = await Runner.run(
                        self.reformatting_agent, str(message_output), context=self.context)
                return messages
            
        return react_inspect()
