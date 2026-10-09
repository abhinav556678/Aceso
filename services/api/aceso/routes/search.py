from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from aceso.db import pool
from aceso.ai.embeddings import embed_text

router = APIRouter()

class SearchRequest(BaseModel):
    query: str
    patient_id: str

@router.post("")
def search_facts(req: SearchRequest):
    query_vec = embed_text(req.query)
    vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"
    
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Hybrid search: semantic similarity (vector) + lexical similarity (pg_trgm)
            # The exact formulation matches pgvector guidelines. Note that `<=>` is cosine distance, so `1 - (<=>)` is cosine similarity.
            cur.execute("""
                SELECT 
                    fc.id, 
                    fc.fact_id, 
                    fc.content,
                    f.display,
                    f.source,
                    f.audio_start_ms,
                    f.audio_end_ms,
                    f.page_no,
                    f.bbox,
                    1.0 - (fc.embedding <=> %s::vector) AS semantic_sim,
                    similarity(fc.content, %s) AS text_sim,
                    f.raw_text
                FROM fact_chunks fc
                JOIN facts f ON fc.fact_id = f.id
                WHERE fc.patient_id = %s
                ORDER BY (1.0 - (fc.embedding <=> %s::vector)) * 0.7 + similarity(fc.content, %s) * 0.3 DESC
                LIMIT 5
            """, (vec_str, req.query, req.patient_id, vec_str, req.query))
            
            results = cur.fetchall()
            
            # Format results
            out = []
            for r in results:
                out.append({
                    "chunk_id": str(r[0]),
                    "fact_id": str(r[1]),
                    "content": r[2],
                    "display": r[3],
                    "source": r[4],
                    "audio_start_ms": r[5],
                    "audio_end_ms": r[6],
                    "page_no": r[7],
                    "bbox": r[8],
                    "semantic_sim": float(r[9]) if r[9] else 0.0,
                    "text_sim": float(r[10]) if r[10] else 0.0,
                    "raw_text": r[11]
                })
                
            # Log the search event as required by auditing guidelines
            # "Log each query to audit_log (action='search.query') — a search through a medical record is an access event."
            # Since this API is internal and unauthenticated in this context, we write a generic system actor or None
            cur.execute("""
                INSERT INTO audit_log (actor_id, actor_label, action, entity_type, patient_id, payload)
                VALUES (NULL, 'system', 'search.query', 'patient', %s, %s)
            """, (req.patient_id, req.query))
                
            return {"results": out}
