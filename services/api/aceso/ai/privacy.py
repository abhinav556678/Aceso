import re
import logging

logger = logging.getLogger(__name__)

def redact_phi(text: str) -> str:
    """
    Privacy gateway: Redacts potential PHI (names, phone numbers, ID numbers) 
    from outbound LLM payloads.
    """
    # 1. Redact phone numbers (simple regex for demo)
    text = re.sub(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', '[REDACTED_PHONE]', text)
    
    # 2. Redact potential MRNs / IDs (e.g. ACE-1234, ID: 12345)
    text = re.sub(r'\b(ACE|MRN|ID)[-:\s]?\d+\b', '[REDACTED_ID]', text, flags=re.IGNORECASE)
    
    # 3. Dynamic Name Redaction
    # Matches typical two-word capitalized names (e.g., Meena Rajan) 
    # and common titles (Mr., Mrs., Dr.) followed by a name.
    text = re.sub(r'\b(?:Mr\.|Mrs\.|Dr\.)?\s?[A-Z][a-z]+\s[A-Z][a-z]+\b', '[REDACTED_NAME]', text)
    text = re.sub(r'\b[A-Z][a-z]+\b(?=\s+is\s+a\s+\d+\s+year\s+old)', '[REDACTED_NAME]', text)
    
    # 4. Redact general numbers that might be PHI (excluding small numbers for age/values)
    # We will just redact large numbers (4+ digits) to be safe.
    text = re.sub(r'\b\d{4,}\b', '[REDACTED_NUMBER]', text)
    
    return text
