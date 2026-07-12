from pydantic import BaseModel


class KnowledgeSource(BaseModel):
    knowledge_base_id: str
    knowledge_base_name: str
    document_id: str
    document_name: str
    chunk_id: str
    excerpt: str
    similarity: float
