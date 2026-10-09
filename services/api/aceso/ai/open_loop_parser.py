import re
import datetime
from typing import List, Dict, Any

def extract_followup_days(text: str) -> int:
    """Extract due date in days from clinical text."""
    text = text.lower()
    if "month" in text:
        match = re.search(r'(\d+)\s*month', text)
        return int(match.group(1)) * 30 if match else 90
    elif "week" in text:
        match = re.search(r'(\d+)\s*week', text)
        return int(match.group(1)) * 7 if match else 14
    return 30

def parse_open_loops_from_plan(plan_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse follow-up tasks from plan notes."""
    followups = []
    keywords = ["repeat", "recheck", "follow", "due", "refer"]
    
    for item in plan_items:
        text = item.get("text", "").lower()
        if any(kw in text for kw in keywords):
            days = extract_followup_days(text)
            due_date = datetime.date.today() + datetime.timedelta(days=days)
            fact_ids = item.get("fact_ids", [])
            fact_id = fact_ids[0] if fact_ids else None
            
            followups.append({
                "description": item["text"],
                "due_date": due_date,
                "fact_id": fact_id
            })
            
    return followups
