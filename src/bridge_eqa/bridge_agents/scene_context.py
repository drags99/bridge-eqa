from dataclasses import dataclass
from typing import Any, Optional
from bridge_eqa.bridge_agents.scene_graph_schema import SceneGraph
from pathlib import Path
from bridge_eqa.bridge_inspection_schemas import NbiScore


@dataclass
class SceneContext:
    """Context for scene analysis operations."""
    project_id: str
    session_id: str
    node_to_image_mapping: dict[int, str]
    current_position: int = 0  # Current node ID in the scene graph
    project_path: Optional[Path] = None  # use as fallback to find data
    scene_graph: Optional[SceneGraph] = None
    oracle_calls: int = 0
    max_oracle_calls: int = 5
    tool_model_name: str = "litellm/openrouter/google/gemini-2.5-flash-lite"
    image_context: Optional[list[dict]] = None
    question: Optional[str] = None
    reference_answer: Optional[str] = None
    reference_condition_rating: Optional[NbiScore] = None

