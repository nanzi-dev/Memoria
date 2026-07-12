from concurrent.futures import ThreadPoolExecutor
import sys
import threading
import time
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


def test_vector_store_singleton_initializes_once_under_concurrency(monkeypatch):
    from memoria.core import vector_memory

    created = []
    created_lock = threading.Lock()
    start = threading.Barrier(8)

    class FakeStore:
        def __init__(self):
            with created_lock:
                created.append(self)
            time.sleep(0.02)

    monkeypatch.setattr(vector_memory, "_vector_store_instance", None)
    monkeypatch.setattr(vector_memory, "VectorMemoryStore", FakeStore)

    def get_store():
        start.wait()
        return vector_memory.get_vector_store()

    with ThreadPoolExecutor(max_workers=8) as executor:
        stores = list(executor.map(lambda _: get_store(), range(8)))

    assert len(created) == 1
    assert all(store is stores[0] for store in stores)
