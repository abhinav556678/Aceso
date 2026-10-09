import logging
from typing import List, Dict, Any
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

class VerificationStrategy:
    def verify(self, fact: Dict[str, Any], result_data: Dict[str, Any]) -> float:
        raise NotImplementedError
    def get_full_text(self, result_data: Dict[str, Any]) -> str:
        raise NotImplementedError

class DocumentVerifier(VerificationStrategy):
    def verify(self, fact: Dict[str, Any], result_data: Dict[str, Any]) -> float:
        evidence = fact.get('evidence_text', '').lower()
        if not evidence:
            return 0.0
            
        best_score = 0.0
        best_bbox = None
        best_page = None
        
        pages = result_data.get('pages', [])
        for page in pages:
            for block in page.get('blocks', []):
                block_text = block.get('text', '').lower()
                score = fuzz.partial_ratio(evidence, block_text)
                if score > best_score:
                    best_score = score
                    best_bbox = {
                        'x': block.get('x'),
                        'y': block.get('y'),
                        'w': block.get('w'),
                        'h': block.get('h')
                    }
                    best_page = page.get('page_number')
                    
        if best_score > 80 and best_bbox:
            fact['bbox'] = best_bbox
            fact['page_no'] = best_page
            
        return best_score / 100.0

    def get_full_text(self, result_data: Dict[str, Any]) -> str:
        return result_data.get('text', '').lower()

class AudioVerifier(VerificationStrategy):
    def verify(self, fact: Dict[str, Any], result_data: Dict[str, Any]) -> float:
        evidence = fact.get('evidence_text', '').lower()
        if not evidence:
            return 0.0
            
        transcript = result_data.get('transcript', '').lower()
        score = fuzz.partial_ratio(evidence, transcript)
        
        best_segment = None
        best_seg_score = 0.0
        for segment in result_data.get('segments', []):
            seg_score = fuzz.partial_ratio(evidence, segment.get('text', '').lower())
            if seg_score > best_seg_score:
                best_seg_score = seg_score
                best_segment = segment
                
        if best_seg_score > 80 and best_segment:
            fact['audio_start_ms'] = int(best_segment.get('start', 0) * 1000)
            fact['audio_end_ms'] = int(best_segment.get('end', 0) * 1000)
            
        return max(score, best_seg_score) / 100.0

    def get_full_text(self, result_data: Dict[str, Any]) -> str:
        return result_data.get('transcript', '').lower()


def get_verifier(source_type: str) -> VerificationStrategy:
    if source_type == 'document':
        return DocumentVerifier()
    elif source_type == 'audio':
        return AudioVerifier()
    raise ValueError(f"Unknown source type: {source_type}")


def verify_facts(structured_facts: List[Dict[str, Any]], source_type: str, result_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    verified_facts = []
    strategy = get_verifier(source_type)
    
    for fact in structured_facts:
        confidence = strategy.verify(fact, result_data)
        fact['confidence'] = round(confidence, 2)
        if confidence > 0.8:
            fact['state'] = 'verified'
        else:
            fact['state'] = 'needs_attention'
        verified_facts.append(fact)
        
    full_text = strategy.get_full_text(result_data)
    
    critical_terms = ["cancer", "tumor", "severe", "critical", "allergy", "anaphylaxis", "fracture", "myocardial", "infarction", "hemorrhage", "stroke"]
    
    for term in critical_terms:
        if fuzz.partial_ratio(term, full_text) > 90:
            mentioned = any(fuzz.partial_ratio(term, str(f.get('display', '')).lower()) > 80 or 
                            fuzz.partial_ratio(term, str(f.get('evidence_text', '')).lower()) > 80 
                            for f in verified_facts)
            
            if not mentioned:
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
