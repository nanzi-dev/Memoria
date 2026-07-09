import sys
import types

from memoria.core.vector_memory import VectorMemoryStore


class FakeEmbedding:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class FailingCudaModel:
    def encode(self, text):
        raise RuntimeError("CUDA error: unspecified launch failure")


class CpuModel:
    def encode(self, text):
        return FakeEmbedding([0.1, 0.2, 0.3])


def test_encode_text_recovers_cuda_failure_to_cpu(monkeypatch):
    created = {}

    def fake_sentence_transformer(model_name, device=None):
        created["model_name"] = model_name
        created["device"] = device
        return CpuModel()

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=fake_sentence_transformer),
    )

    store = VectorMemoryStore.__new__(VectorMemoryStore)
    store.embedding_model = FailingCudaModel()
    store.embedding_device = "cuda:0"
    store.embedding_disabled = False

    assert store._encode_text("hello") == [0.1, 0.2, 0.3]
    assert store.embedding_device == "cpu"
    assert store.embedding_disabled is False
    assert created["device"] == "cpu"


def test_disabled_embedding_skips_vector_operations():
    store = VectorMemoryStore.__new__(VectorMemoryStore)
    store.embedding_disabled = True

    assert store.search_similar_memories("npc", "player", "query") == []
    assert store.add_memory(1, "npc", "player", "fact") is False
