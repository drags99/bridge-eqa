"""Enhanced scene graph models for multi-agent scene understanding with spatial context."""

from pydantic import BaseModel, Field
from typing import List, Optional


class EdgeConnection(BaseModel):
    """Enhanced edge connection between nodes with descriptive relationships."""

    connected_to: str = Field(description="Name/ID of the connected node")
    description_of_connection: str = Field(
        description="Detailed description of how nodes are connected"
    )


class Node(BaseModel):
    """Enhanced node in the scene graph with spatial context and detailed descriptions."""

    image_name: str = Field(description="Name of the image file")
    central_focus: str = Field(description="The main subject or focus of the image")
    image_description: str = Field(
        description="Detailed description of what's visible in the image"
    )
    edges: List[EdgeConnection] = Field(description="edge connections to other nodes")
    object_id: Optional[str] = Field(
        default=None,
        description="Unique identifier for the physical object shown (e.g., 'beam_1', 'pier_2'). "
        "Multiple nodes can share the same object_id if they show the same physical component from different angles."
    )
    object_type: Optional[str] = Field(
        default=None,
        description="Type of physical object (e.g., 'beam', 'pier', 'deck', 'bearing', 'abutment')"
    )


class SceneGraph(BaseModel):
    """Complete enhanced scene graph with spatial context and multi-agent support."""

    nodes: List[Node] = Field(
        description="All scene nodes in the graph"
    )
