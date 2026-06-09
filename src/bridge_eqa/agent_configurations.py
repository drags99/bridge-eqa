from dataclasses import dataclass
from bridge_eqa.bridge_agents.base_inspection_agent import InspectionAgent
from bridge_eqa.bridge_agents.embodied.agent import EmbodiedInspectionAgent
from bridge_eqa.bridge_agents.tools.map import scene_graph_interface_tool
from bridge_eqa.bridge_agents.tools.oracle import oracle_tool
from bridge_eqa.bridge_agents.scene_context import SceneContext
from typing import List
from agents import Tool
import logfire

AgentName = str
AgentMessages = List[dict]


@dataclass
class AgentConfig:
    """Configuration for an agent variant in the evaluation."""
    architecture: str
    tools: List[Tool]  # List of tools available to the agent
    context_type: str  # "images", "sg_context", or "both"

AGENT_CONFIGS = {
    "embodied_no_tools_images": AgentConfig("embodied", [], "images"),
    "embodied_no_tools_sg_context": AgentConfig("embodied", [], "sg_context"),
    "embodied_no_tools_both": AgentConfig("embodied", [], "both"),

    "embodied_sg_oracle_sg_context": AgentConfig("embodied", [scene_graph_interface_tool, oracle_tool], "sg_context"),
    "embodied_sg_oracle_both": AgentConfig("embodied", [scene_graph_interface_tool, oracle_tool], "both"),
}


# Agent class mapping, can be used to extend to other architectures in the future
AGENT_CLASS_MAP = {
    "embodied": EmbodiedInspectionAgent,
}


def create_agent_from_config(
    agent_name: str,
    scene_context: SceneContext,
    model_name: str,
    question: str,
    image_context: list,
    scene_graph_context: list
) -> tuple[InspectionAgent, AgentMessages]:
    """Create an agent and its messages from a configuration name.

    Args:
        agent_name: Name of the agent configuration (key in AGENT_CONFIGS)
        scene_context: Scene context object
        model_name: Name of the model to use
        question: The question/task for the agent
        image_context: Raw image data context
        scene_graph_context: Scene graph JSON context

    Returns:
        Tuple of (agent instance, messages list)

    Raises:
        KeyError: If agent_name is not in AGENT_CONFIGS
    """
    if agent_name not in AGENT_CONFIGS:
        raise KeyError(f"Unknown agent configuration: {agent_name}. Available: {list(AGENT_CONFIGS.keys())}")

    config = AGENT_CONFIGS[agent_name]

    # Select agent class based on architecture
    agent_class = AGENT_CLASS_MAP[config.architecture]

    logfire.info(f"Creating agent {agent_name}")

    # Create agent instance
    agent = agent_class(
        model_name=model_name,
        context=scene_context,
        tools=config.tools
    )

    # Build messages based on context type
    if config.context_type == "sg_context":
        # Scene graph context only
        messages = [
            {
                "role": "user",
                "content": scene_graph_context,
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": question},
                ]
            }
        ]
    elif config.context_type == "images":
        # Image context only
        messages = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "image data"}] + image_context,
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": question},
                ]
            }
        ]
    elif config.context_type == "both":
        # Both scene graph and image context
        messages = [
            {
                "role": "user",
                "content": scene_graph_context,
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "image data"}] + image_context,
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": question},
                ]
            }
        ]
    else:
        raise ValueError(f"Unknown context_type: {config.context_type}. Must be 'images', 'sg_context', or 'both'")

    return agent, messages


def get_agents_for_experiments(
    scene_context: SceneContext,
    model_name: str,
    question: str,
    image_context: list,
    scene_graph_context: list
) -> tuple[List[InspectionAgent], List[AgentMessages], List[AgentName]]:
    """Create all agent variants for the experiment.

    Args:
        scene_context: Scene context object
        model_name: Name of the model to use
        question: The question/task for the agents
        image_context: Raw image data context
        scene_graph_context: Scene graph JSON context

    Returns:
        Tuple of (agents list, messages list, agent names list)
    """
    eval_agents = []
    eval_agents_messages = []
    eval_agents_names = []

    for agent_name in AGENT_CONFIGS.keys():
        agent, messages = create_agent_from_config(
            agent_name=agent_name,
            scene_context=scene_context,
            model_name=model_name,
            question=question,
            image_context=image_context,
            scene_graph_context=scene_graph_context
        )
        eval_agents.append(agent)
        eval_agents_messages.append(messages)
        eval_agents_names.append(agent_name)

    return eval_agents, eval_agents_messages, eval_agents_names
