from agents import function_tool, RunContextWrapper, ModelSettings
from pydantic import BaseModel
from pydantic import Field
import json
import hashlib
from bridge_eqa.bridge_agents.scene_graph_schema import (
    SceneGraph,
    Node,
)
from agents import Agent, Runner
import logfire
from bridge_eqa.bridge_agents.scene_context import SceneContext
from bridge_eqa.bridge_agents.agent_prompts import (
    SCENE_GRAPH_INTERFACE_AGENT_PROMPT,
)
from dotenv import load_dotenv

load_dotenv()


@function_tool
async def move_to_node(
    wrapper: RunContextWrapper[SceneContext], target_node_index: int
) -> str:
    """Move the agent to a specific node in the scene graph.

    Navigate to a different viewpoint or location in the 3D scene.
    Updates the agent's current position to enable exploration from the new perspective.

    Args:
        target_node_index: int Index of the node to move to (0-based)
    """

    context = wrapper.context
    scene_graph = context.scene_graph

    if target_node_index < 0 or target_node_index >= len(scene_graph.nodes):
        return f"Error: Invalid node index {target_node_index}. Scene has {len(scene_graph.nodes)} nodes (0-{len(scene_graph.nodes) - 1})."

    # # target_node must exist in the scene graph
    # if target_node not in scene_graph.nodes:
    #     logfire.warn(f"Target node {target_node} does not exist in the current scene graph")
    #     return f"Target node {target_node} does not exist in the current scene graph, you can only move to nodes that exist in the scene graph, the node at target_node_index is {scene_graph.nodes[target_node_index]}"

    logfire.info(f"Moving to node {target_node_index} from {context.current_position}")
    previous_position = context.current_position
    context.current_position = target_node_index

    target_node = scene_graph.nodes[target_node_index]
    logfire.info(f"Moved from node {previous_position} to node {target_node_index}")

    return f"Successfully moved to node {target_node_index}: {target_node.central_focus}. Current view: {target_node.image_description}"


@function_tool
def update_node_information(
    wrapper: RunContextWrapper[SceneContext],
    node_idx_to_update: int,
    old_node: Node,
    new_node: Node,
) -> str:
    """Update scene graph node with new observations or corrections.

    Use this tool to modify node information when:
    - New damage or features are discovered during inspection
    - Initial descriptions need refinement or correction
    - Spatial relationships change or need updating
    - Additional context becomes available from analysis

    Args:
        node_idx_to_update: Index of the node to update (0-based)
        new_node: Complete updated node object with all fields
    """

    # old_node must exist in the scene graph
    if old_node not in wrapper.context.scene_graph.nodes:
        logfire.error(f"Old node {old_node} does not exist in the current scene graph")
        return f"Old node {old_node} does not exist in the current scene graph, you can only update nodes that exist in the scene graph."

    if node_idx_to_update >= len(wrapper.context.scene_graph.nodes):
        logfire.error(
            f"Node index {node_idx_to_update} is out of bounds for the current scene graph"
        )
        return f"Node index {node_idx_to_update} is out of bounds for the current scene graph"

    context = wrapper.context
    scene_graph = context.scene_graph
    scene_graph.nodes[node_idx_to_update] = new_node
    context.scene_graph = scene_graph

    # Broadcast change to frontend via WebSocket
    if context.websocket:
        try:
            import asyncio
            asyncio.create_task(context.websocket.send_json({
                "type": "scene_graph_updated",
                "node_idx": node_idx_to_update,
                "node": new_node.model_dump(),
                "updated_by": "agent"
            }))
            logfire.info(f"Broadcasted scene graph update for node {node_idx_to_update}")
        except Exception as e:
            logfire.warn(f"Failed to broadcast scene graph update: {e}")

    return f"Successfully updated node information for node index: {node_idx_to_update}, new scene graph: {scene_graph.model_dump_json()}"


class SceneGraphMapInterfaceResponse(BaseModel):
    response: str = Field(description="The response to the question")


@function_tool
async def scene_graph_interface_tool(
    wrapper: RunContextWrapper[SceneContext], question: str, node_indices: list[int]
) -> str:
    """Natural language interface for scene navigation and visual analysis.

    Navigate 3D scenes and analyze bridge conditions using conversational commands.
    Can analyze up to 16 images simultaneously for comparative inspection.
    The tool will move the agent to the first node in node_indices if provided. Analysis can then be performed on multiple nodes. The oracle will only see the image that you have positioned yourself at using this tool.

    **Navigation**:
    - "Move to the north pier"
    - "Go to node 5"
    - "Navigate to the deck surface"

    **Visual Analysis** (single or multi-image):
    - "What damage is visible here?" (analyzes current node image)
    - "Compare corrosion at nodes 3, 7, and 12" (analyzes up to 4 images)
    - "Show me rust patterns across nodes 5-8" (analyzes specified nodes)
    - "Is the cracking worse at node 10 or node 15?" (comparative analysis)
    - "Describe conditions at nodes 2, 6, and 9" (multi-node inspection)

    **Returns**: Brief response (30-50 words typical) with essential findings.

    Args:
        question: Navigation command, visual query, or comparative analysis request.
               Can reference multiple nodes for multi-image comparison (max 16 images).
        node_indices: List of node indices (0-based integers) to analyze. Empty list defaults to current position.
                     Maximum 16 nodes will be analyzed.
    """
    # load scene graph from context
    context = wrapper.context

    if not context.scene_graph:
        scene_graph_path = context.project_path / "scene_graph.json"

        with open(scene_graph_path, "r") as f:
            scene_graph = json.load(f)
        context.scene_graph = SceneGraph.model_validate(scene_graph)
    scene_graph = context.scene_graph

    # Use provided node indices, default to current position if empty
    mentioned_nodes = node_indices if node_indices else [context.current_position]
    # Limit to 16 nodes and ensure valid indices
    mentioned_nodes = [n for n in mentioned_nodes if 0 <= n < len(scene_graph.nodes)][:16]

    logfire.info(f"Scene graph interface analyzing nodes: {mentioned_nodes}")

    # Create cache key from question, node indices, and model
    cache_key = hashlib.sha256(json.dumps({
        "question": question.strip(),
        "node_indices": sorted(mentioned_nodes),
        "model": context.tool_model_name,
        "scene_graph_hash": hashlib.sha256(scene_graph.model_dump_json().encode()).hexdigest()[:16]
    }, sort_keys=True).encode()).hexdigest()

    agent = Agent(
        name="Scene Graph Interface",
        model=context.tool_model_name,
        tools=[move_to_node, update_node_information],
        instructions=SCENE_GRAPH_INTERFACE_AGENT_PROMPT,
        model_settings=ModelSettings(temperature=0),
    )
    result = await Runner.run(agent, question, context=context)

    # Cache the response
    response = str(result.final_output)
    logfire.info(f"Scene graph interface response cached for question: {question[:50]}...")

    # Return concise response without redundant node information
    return response
