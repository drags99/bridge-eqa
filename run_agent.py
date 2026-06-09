"""Run the embodied_sg_oracle_both agent against a single BridgeEQA test question.

Loads a QA row from BridgeEQA_2025/test.db, builds the scene context (images +
scene graph) for the referenced bridge, and runs the agent against it.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import dotenv
import logfire

from bridge_eqa.agent_configurations import AGENT_CONFIGS, create_agent_from_config
from bridge_eqa.bridge_agents.qa_response import InspectionQuestionAnswerResponse
from bridge_eqa.bridge_agents.scene_context import SceneContext
from bridge_eqa.bridge_agents.scene_graph_schema import SceneGraph
from bridge_eqa.files import CloudFileStorage

DATA_FOLDER = Path("BridgeEQA_2025")
AGENT_NAME = "embodied_sg_oracle_both"
MODEL_NAME = "litellm/openrouter/google/gemini-3.5-flash"

_cloud_storage: Optional[CloudFileStorage] = None


def get_cloud_storage() -> CloudFileStorage:
    """Return a process-wide CloudFileStorage (one S3 client + disk cache)."""
    global _cloud_storage
    if _cloud_storage is None:
        _cloud_storage = CloudFileStorage()
    return _cloud_storage


@dataclass
class QARow:
    """A row from the `test` table in BridgeEQA_2025/test.db."""

    id: int
    bridge: str
    question: str
    answer: str
    reference_images: list[str]
    condition_rating: Optional[int]

    @property
    def scene_dir(self) -> Path:
        return DATA_FOLDER / self.bridge


def load_qa_row(db_path: Path, row_index: int = 0) -> QARow:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM test ORDER BY id LIMIT 1 OFFSET ?", (row_index,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise IndexError(f"No QA row at index {row_index} in {db_path}")

    return QARow(
        id=row["id"],
        bridge=row["bridge"],
        question=row["question"],
        answer=row["answer"],
        reference_images=json.loads(row["reference_images"]),
        condition_rating=row["condition_rating"],
    )


def create_node_and_image_url_mapping(
    scene_dir: Path, scene_graph: SceneGraph
) -> dict[int, str]:
    """Map each scene-graph node index to a presigned image URL."""
    image_dir = scene_dir / "images"
    cfs = get_cloud_storage()
    return {
        idx: cfs.get_download_url(image_dir / node.image_name).download_url
        for idx, node in enumerate(scene_graph.nodes)
    }


def prepare_images_for_prompt(scene_dir: Path) -> list[dict]:
    """Upload bridge images and build the multimodal image-context blocks."""
    cfs = get_cloud_storage()
    images: list[dict] = []
    for image_path in sorted((scene_dir / "images").iterdir()):
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        response = cfs.get_download_url(image_path)
        images.append({"type": "input_image", "image_url": response.download_url})
        images.append(
            {"type": "input_text", "text": f"Image name: {Path(response.local_file_path).name}"}
        )
    return images


def build_scene_context(qa: QARow) -> tuple[SceneContext, list[dict], list[dict]]:
    """Build the SceneContext and the image / scene-graph message context."""
    scene_dir = qa.scene_dir
    scene_graph = SceneGraph.model_validate_json(
        (scene_dir / "scene_graph.json").read_text()
    )

    image_context = prepare_images_for_prompt(scene_dir)
    node_summary = "\n".join(
        f"Node index {i} maps to image: {node.image_name}"
        for i, node in enumerate(scene_graph.nodes)
    )
    scene_graph_context = [
        {
            "type": "input_text",
            "text": f"The current scene graph is: {scene_graph.model_dump_json()}\n {node_summary} ",
        }
    ]

    scene_context = SceneContext(
        project_id=qa.bridge,
        session_id=qa.bridge,
        project_path=scene_dir,
        scene_graph=scene_graph,
        max_oracle_calls=2,
        image_context=image_context,
        tool_model_name=MODEL_NAME,
        node_to_image_mapping=create_node_and_image_url_mapping(scene_dir, scene_graph),
        question=qa.question,
    )
    return scene_context, image_context, scene_graph_context


def format_question(qa: QARow) -> str:
    """Append the condition-rating instruction expected by the agent."""
    requirement = "optional" if qa.condition_rating is None else "required"
    return f"{qa.question}. A numerical value for the condition rating is {requirement}."


async def run_agent(qa: QARow) -> InspectionQuestionAnswerResponse:
    scene_context, image_context, scene_graph_context = build_scene_context(qa)

    agent, messages = create_agent_from_config(
        agent_name=AGENT_NAME,
        scene_context=scene_context,
        model_name=MODEL_NAME,
        question=format_question(qa),
        image_context=image_context,
        scene_graph_context=scene_graph_context,
    )

    result = await agent.async_inspect(messages)
    return result.final_output


async def main() -> None:
    dotenv.load_dotenv()
    logfire.configure()
    logfire.instrument_openai_agents()

    assert AGENT_NAME in AGENT_CONFIGS, f"unknown agent config: {AGENT_NAME}"

    qa = load_qa_row(DATA_FOLDER / "test.db", row_index=0)
    logfire.info(f"Running {AGENT_NAME} on QA #{qa.id} ({qa.bridge})")

    output = await run_agent(qa)
    rating = output.condition_rating.score if output.condition_rating else None

    logfire.info(
        "Agent answer for QA #{qa_id}",
        qa_id=qa.id,
        answer=output.answer,
        condition_rating=rating,
        reference_images=output.reference_images,
        ground_truth_answer=qa.answer,
        ground_truth_condition_rating=qa.condition_rating,
    )
    print(f"Question:{qa.question}")
    print(f"Agent Answer:{output.answer}")
    print(f"Agent Condition Rating:{rating}")
    print(f"Ground Truth Answer:{qa.answer}")
    print(f"Ground Truth Condition Rating:{qa.condition_rating}")

if __name__ == "__main__":
    asyncio.run(main())