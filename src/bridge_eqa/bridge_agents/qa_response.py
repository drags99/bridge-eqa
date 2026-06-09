from pydantic import BaseModel, Field
from typing import Optional, List
from bridge_eqa.bridge_inspection_schemas import NbiScore

class InspectionQuestionAnswerResponse(BaseModel):
    answer: str = Field(..., description="Answer to a user's question")
    reference_images: Optional[List[str]] = Field(
        None, description="Optional reference images that are referenced in the answer"
    )
    condition_rating: Optional[NbiScore] = Field(
        None, description="Relevant NBI Condition rating for the answer when requested. This should be None if not applicable."
    )
