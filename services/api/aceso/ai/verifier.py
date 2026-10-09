import logging
import uuid
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def verify_facts(structured_facts: List[Dict[str, Any]], source_type: str, result_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Three-Way Verification Engine.
    Cross-checks extracted facts against OCR/STT output.
    """
    verified_facts = []
    
    # 1. & 2. Verify extracted facts
    for fact in structured_facts:
        confidence = 0.0
        evidence = fact.get('evidence_text', '').lower()
        
        if not evidence:
            pass
        elif source_type == 'document':
            # OCR match check
            pages = result_data.get('pages', [])
            found = False
            for page in pages:
                # Check blocks
                for block in page.get('blocks', []):
                    if evidence in block.get('text', '').lower():
                        found = True
                        break
                if found: break
                
                # Fallback to page text
                if evidence in page.get('text', '').lower():
                    found = True
                    break
                    
            if found:
                confidence = 0.95
            else:
                confidence = 0.3
                
        elif source_type == 'audio':
            # Transcript support check
            transcript = result_data.get('transcript', '').lower()
            if evidence in transcript:
                confidence = 0.95
            else:
                confidence = 0.3
                
        fact['confidence'] = confidence
        if confidence > 0.8:
            fact['state'] = 'verified'
        else:
            fact['state'] = 'needs_attention'
            
        verified_facts.append(fact)
        
    # 3. Omission check (high-recall pass)
    # Check full text for common critical terms that might be missed
    full_text = ""
    if source_type == 'document':
        full_text = result_data.get('text', '').lower()
    elif source_type == 'audio':
        full_text = result_data.get('transcript', '').lower()
        
    critical_terms = ["cancer", "tumor", "severe", "critical", "allergy", "anaphylaxis", "fracture", "myocardial"]
    
    # Simple check: if a critical term is in the text but no fact mentions it
    for term in critical_terms:
        if term in full_text:
            # Check if any fact mentions it
            mentioned = False
            for fact in verified_facts:
                if term in str(fact.get('display', '')).lower() or term in str(fact.get('evidence_text', '')).lower():
                    mentioned = True
                    break
            
            if not mentioned:
                # Flag as omitted fact
                omission = {
                    'fact_type': 'omission_warning',
                    'display': f"Potential omission detected: {term}",
                    'value_num': None,
                    'unit': None,
                    'evidence_text': f"...{term}...",
                    'source_type': source_type,
                    'normalized_code': None,
                    'normalized_system': None,
                    'state': 'needs_attention',
                    'confidence': 0.0
                }
                verified_facts.append(omission)
                
    return verified_facts
