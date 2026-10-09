import json
import logging
from typing import List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class ExtractedFact(BaseModel):
    fact_type: str = Field(..., description="E.g., medication, allergy, lab_result")
    display: str = Field(..., description="The main text of the fact")
    value_num: Optional[float] = None
    unit: Optional[str] = None
    evidence_text: str = Field(..., description="The exact text snippet that justifies this fact")

def extract_facts(text: str, source_type: str) -> List[ExtractedFact]:
    """
    Simulates an LLM extracting clinical facts from text.
    In a real implementation, you'd use LangChain/Instructor with an LLM.
    """
    logger.info(f"Extracting facts from {source_type} text of length {len(text)}")
    
    # Mocked facts based on input
    facts = []
    text_lower = text.lower()
    
    if "metformin" in text_lower or "glycomet" in text_lower:
        facts.append(ExtractedFact(
            fact_type="medication",
            display="Metformin 500 mg",
            value_num=500.0,
            unit="mg",
            evidence_text="Metformin 500" if "metformin 500" in text_lower else "Glycomet"
        ))
        
    if "penicillin" in text_lower:
        facts.append(ExtractedFact(
            fact_type="allergy",
            display="Penicillin",
            evidence_text="Penicillin"
        ))
        
    if "a1c" in text_lower or "hba1c" in text_lower:
        facts.append(ExtractedFact(
            fact_type="lab_result",
            display="HbA1c",
            value_num=7.2,
            unit="%",
            evidence_text="HbA1c"
        ))
        
    # Always extract at least one mock fact if nothing matches
    if not facts:
        facts.append(ExtractedFact(
            fact_type="condition",
            display="Hypertension",
            evidence_text=text[:15] if len(text) > 15 else text
        ))
        
    return facts
