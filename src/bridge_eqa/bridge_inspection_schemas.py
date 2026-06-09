from typing import Union
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class NbiScore(BaseModel):
    score: Union[int, None] = Field(
        None,
        description="""
        Leave empty if the score is not applicable.
        NBI condition rating (0-9):
        9 - Excellent condition
        8 - Very good condition
        7 - Good condition - some minor problems
        6 - Satisfactory condition - minor deterioration of structural elements (limited)
        5 - Fair condition - minor deterioration of structural elements (extensive)
        4 - Poor condition - deterioration significantly affects structural capacity
        3 - Serious condition - deterioration seriously affects structural capacity
        2 - Critical condition - bridge should be closed until repaired
        1 - Failing condition - bridge closed but repairable
        0 - Failed condition - bridge closed but beyond repair
        None - Not applicable or cannot be determined
        """,
    )

ComponentName = Literal[
    "Deck", "Superstructure", "Substructure", "Channel", "Culverts", "Approach"
]