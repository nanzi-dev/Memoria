# 知识库检索评测

## 2026-07-13 准确性基线

评测对象：

- 用户：`usr_0de62486`
- 知识库：`d47380cb-90e7-4ba3-9082-96d09a88d384`
- 数据集：`tests/fixtures/knowledge_retrieval_zh.json`
- 问题数：45
- 参与检索的 SQL 分块数：147

真实 SQL + Chroma 混合检索结果：

| 指标 | 结果 | 验收线 |
| --- | ---: | ---: |
| Recall@5 | 1.000 | >= 0.90 |
| MRR | 1.000 | >= 0.80 |
| 表格查询 Top 3 | 1.000 | 1.000 |
| 重复上下文比例 | 0.000 | < 0.10 |

运行命令：

```bash
.venv/bin/python scripts/evaluate_knowledge_retrieval.py \
  --owner-user-id usr_0de62486 \
  --knowledge-base-id d47380cb-90e7-4ba3-9082-96d09a88d384
```

## 嵌入模型对比

在同一批分块和问题上比较纯向量检索及最终混合检索。候选模型为
`BAAI/bge-small-zh-v1.5`；带前缀的实验使用模型建议的中文短查询检索前缀。

```bash
.venv/bin/python scripts/compare_knowledge_embeddings.py \
  --owner-user-id usr_0de62486 \
  --knowledge-base-id d47380cb-90e7-4ba3-9082-96d09a88d384 \
  --model current=models/sentence-transformers/all-MiniLM-L6-v2 \
  --model bge-no-prefix=/path/to/bge-small-zh-v1.5 \
  --model bge-instructed=/path/to/bge-small-zh-v1.5 \
  --query-prefix bge-instructed=为这个句子生成表示以用于检索相关文章：
```

| 模型 | 纯向量 Recall@5 | 纯向量 MRR@5 | 混合 Recall@5 | 混合 MRR |
| --- | ---: | ---: | ---: | ---: |
| all-MiniLM-L6-v2 | 0.356 | 0.199 | 1.000 | 1.000 |
| bge-small-zh-v1.5，无前缀 | 0.667 | 0.417 | 1.000 | 1.000 |
| bge-small-zh-v1.5，查询前缀 | 0.667 | 0.419 | 1.000 | 1.000 |

### 决策

当前默认模型暂不迁移。BGE 的纯向量召回明显更高，但在当前 45 问评测上没有提高
最终混合检索指标。它的向量维度为 512，现有模型为 384；直接切换会使已有 Chroma
集合维度不兼容，并要求长期记忆和知识库向量全部重建。候选模型体积约 184 MiB，
现有本地模型约 88 MiB，也会增加部署成本。

后续迁移应满足以下条件：

1. 增加不包含答案原词的语义改写、错别字和跨段归纳问题。
2. BGE 在扩展评测集的最终混合指标上有稳定收益，而不只是纯向量指标提升。
3. 为不同嵌入维度使用版本化集合，并提供完整重建和回滚流程。

在满足这些条件前，继续使用当前模型、结构化分块和 SQL 词法 + Chroma 向量混合
检索，避免以全局向量迁移换取当前用户不可见的指标变化。
