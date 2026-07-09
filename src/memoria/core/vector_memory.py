"""
向量记忆存储模块

用途：
1. 将长期记忆转换为向量并存储到 ChromaDB
2. 基于语义相似度检索相关记忆
3. 提升记忆召回的相关性和准确度
"""

import logging
import os
from typing import List, Optional
# import chromadb  # lazy
# from chromadb.config import Settings  # lazy
# from sentence_transformers import SentenceTransformer  # lazy

from memoria.core.config import configs

# 设置 HuggingFace 镜像以加速模型下载
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

# 禁用 ChromaDB 遥测
os.environ['ANONYMIZED_TELEMETRY'] = 'False'

logger = logging.getLogger(__name__)

# 抑制 ChromaDB 遥测错误日志
logging.getLogger('chromadb.telemetry').setLevel(logging.CRITICAL)

CUDA_ERROR_MARKERS = (
    "cuda",
    "cublas",
    "cudnn",
    "device-side assert",
    "unspecified launch failure",
    "torch_use_cuda_dsa",
)


class VectorMemoryStore:
    """向量记忆存储管理类"""
    
    def __init__(self):
        """初始化向量数据库和嵌入模型(懒加载)"""
        import chromadb
        from chromadb.config import Settings
        from sentence_transformers import SentenceTransformer
        try:
            # 初始化 ChromaDB 客户端（持久化模式）
            # 注意：必须使用 PersistentClient 而不是 Client
            self.client = chromadb.PersistentClient(
                path=configs.vector_db_path,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                    is_persistent=True
                )
            )
            
            # 获取或创建集合
            self.collection = self.client.get_or_create_collection(
                name="long_term_memory",
                metadata={"hnsw:space": "cosine"}  # 使用余弦相似度
            )
            
            # 初始化嵌入模型（轻量级，适合本地部署）
            self.embedding_model = SentenceTransformer(configs.embedding_model)
            self.embedding_device = str(getattr(self.embedding_model, "device", "auto"))
            self.embedding_disabled = False
            
            logger.info(f"向量数据库初始化成功，路径：{configs.vector_db_path}")
            
        except Exception as e:
            logger.error(f"向量数据库初始化失败: {e}")
            raise
    
    def _generate_id(self, character_id: str, player_id: str, fact_id: int) -> str:
        """生成唯一的向量 ID"""
        return f"{character_id}::{player_id}::{fact_id}"
    
    def _parse_id(self, vector_id: str) -> tuple[str, str, int]:
        """解析向量 ID"""
        parts = vector_id.split("::")
        return parts[0], parts[1], int(parts[2])

    def _is_cuda_error(self, error: Exception) -> bool:
        """判断异常是否来自 CUDA / GPU 运行时。"""
        message = str(error).lower()
        return any(marker in message for marker in CUDA_ERROR_MARKERS)

    def _is_cpu_embedding(self) -> bool:
        """当前嵌入模型是否已经在 CPU 上运行。"""
        return self.embedding_device.lower().startswith("cpu")

    def _recover_embedding_model_to_cpu(self) -> bool:
        """CUDA 失败后重建 CPU 嵌入模型，避免后续请求持续失败。"""
        if self._is_cpu_embedding():
            return True

        try:
            from sentence_transformers import SentenceTransformer

            logger.warning("嵌入模型 CUDA 运行失败，切换到 CPU 后重试")
            self.embedding_model = SentenceTransformer(configs.embedding_model, device="cpu")
            self.embedding_device = "cpu"
            self.embedding_disabled = False
            return True
        except Exception as e:
            self.embedding_disabled = True
            logger.error(f"嵌入模型切换到 CPU 失败，已暂时禁用向量记忆: {e}")
            return False

    def _encode_text(self, text: str) -> list[float]:
        """生成文本向量；CUDA 崩溃时降级到 CPU 并重试一次。"""
        if self.embedding_disabled:
            raise RuntimeError("嵌入模型不可用，向量记忆已暂时禁用")

        try:
            return self.embedding_model.encode(text).tolist()
        except Exception as e:
            if not self._is_cuda_error(e) or self._is_cpu_embedding():
                raise

            if not self._recover_embedding_model_to_cpu():
                raise

            try:
                return self.embedding_model.encode(text).tolist()
            except Exception as retry_error:
                self.embedding_disabled = True
                logger.error(f"嵌入模型 CPU 重试失败，已暂时禁用向量记忆: {retry_error}")
                raise retry_error from e
    
    def add_memory(
        self,
        fact_id: int,
        character_id: str,
        player_id: str,
        fact_text: str,
        importance: int = 5
    ) -> bool:
        """
        添加记忆到向量数据库
        
        Args:
            fact_id: 长期记忆表中的主键 ID
            character_id: 角色 ID
            player_id: 玩家 ID
            fact_text: 记忆内容文本
            importance: 重要性（1-10）
        
        Returns:
            bool: 是否添加成功
        """
        try:
            if self.embedding_disabled:
                logger.debug("嵌入模型不可用，跳过向量记忆写入")
                return False

            vector_id = self._generate_id(character_id, player_id, fact_id)
            
            # 生成文本嵌入向量
            embedding = self._encode_text(fact_text)
            
            # 存储到 ChromaDB
            self.collection.add(
                ids=[vector_id],
                embeddings=[embedding],
                documents=[fact_text],
                metadatas=[{
                    "character_id": character_id,
                    "player_id": player_id,
                    "fact_id": fact_id,
                    "importance": importance
                }]
            )
            
            logger.debug(f"向量记忆已添加: {vector_id}")
            return True
            
        except Exception as e:
            logger.error(f"添加向量记忆失败: {e}")
            return False
    
    def search_similar_memories(
        self,
        character_id: str,
        player_id: str,
        query_text: str,
        top_k: Optional[int] = None
    ) -> List[dict]:
        """
        基于语义相似度搜索相关记忆
        
        Args:
            character_id: 角色 ID
            player_id: 玩家 ID
            query_text: 查询文本（通常是当前对话内容）
            top_k: 返回的最大结果数
        
        Returns:
            List[dict]: 相关记忆列表，每个元素包含 fact_id, fact_text, similarity, importance
        """
        try:
            if self.embedding_disabled:
                logger.debug("嵌入模型不可用，跳过向量检索")
                return []

            if top_k is None:
                top_k = configs.vector_search_top_k
            
            # 生成查询向量
            query_embedding = self._encode_text(query_text)
            
            # 在 ChromaDB 中搜索
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={
                    "$and": [
                        {"character_id": character_id},
                        {"player_id": player_id}
                    ]
                }
            )
            
            # 解析结果
            memories = []
            if results and results['ids'] and len(results['ids'][0]) > 0:
                for i, vector_id in enumerate(results['ids'][0]):
                    metadata = results['metadatas'][0][i]
                    distance = results['distances'][0][i] if 'distances' in results else 0.0
                    
                    # 距离转相似度（cosine distance → similarity）
                    similarity = 1.0 - distance
                    
                    memories.append({
                        "fact_id": metadata["fact_id"],
                        "fact_text": results['documents'][0][i],
                        "similarity": similarity,
                        "importance": metadata.get("importance", 5)
                    })
            
            logger.debug(f"向量检索找到 {len(memories)} 条相关记忆")
            return memories
            
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return []
    
    def delete_memory(
        self,
        character_id: str,
        player_id: str,
        fact_id: int
    ) -> bool:
        """
        删除指定的向量记忆
        
        Args:
            character_id: 角色 ID
            player_id: 玩家 ID
            fact_id: 记忆 ID
        
        Returns:
            bool: 是否删除成功
        """
        try:
            vector_id = self._generate_id(character_id, player_id, fact_id)
            self.collection.delete(ids=[vector_id])
            logger.debug(f"向量记忆已删除: {vector_id}")
            return True
            
        except Exception as e:
            logger.error(f"删除向量记忆失败: {e}")
            return False
    
    def update_memory(
        self,
        fact_id: int,
        character_id: str,
        player_id: str,
        fact_text: str,
        importance: int = 5
    ) -> bool:
        """
        更新向量记忆（先删除再添加）
        
        Args:
            fact_id: 记忆 ID
            character_id: 角色 ID
            player_id: 玩家 ID
            fact_text: 新的记忆内容
            importance: 新的重要性
        
        Returns:
            bool: 是否更新成功
        """
        self.delete_memory(character_id, player_id, fact_id)
        return self.add_memory(fact_id, character_id, player_id, fact_text, importance)
    
    def get_memory_count(
        self,
        character_id: Optional[str] = None,
        player_id: Optional[str] = None
    ) -> int:
        """
        获取记忆数量
        
        Args:
            character_id: 角色 ID（可选，用于筛选）
            player_id: 玩家 ID（可选，用于筛选）
        
        Returns:
            int: 记忆数量
        """
        try:
            if character_id and player_id:
                results = self.collection.get(
                    where={
                        "$and": [
                            {"character_id": character_id},
                            {"player_id": player_id}
                        ]
                    }
                )
                return len(results['ids']) if results and results['ids'] else 0
            else:
                return self.collection.count()
                
        except Exception as e:
            logger.error(f"获取记忆数量失败: {e}")
            return 0


# =========================
# 全局单例
# =========================
_vector_store_instance: Optional[VectorMemoryStore] = None

def get_vector_store() -> VectorMemoryStore:
    """获取向量存储单例"""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorMemoryStore()
    return _vector_store_instance
