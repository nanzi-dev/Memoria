from pydantic import BaseModel, Field


class KnowledgeSource(BaseModel):
    knowledge_base_id: str
    knowledge_base_name: str
    document_id: str
    document_name: str
    chunk_id: str
    excerpt: str
    similarity: float
    vector_similarity: float | None = None
    keyword_score: float | None = None
    hybrid_score: float | None = None
    source_metadata: dict = Field(default_factory=dict)
