function clampUnitScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return 0;
  return Math.min(1, Math.max(0, score));
}

export function getKnowledgeSourceMatch(source = {}) {
  const vectorScore = clampUnitScore(source.vector_similarity ?? source.similarity);
  const keywordScore = clampUnitScore(source.keyword_score);
  const hybridScore = clampUnitScore(source.hybrid_score);

  let label = '语义';
  let score = vectorScore;
  if (keywordScore > vectorScore) {
    label = '关键词';
    score = keywordScore;
  } else if (score === 0 && hybridScore > 0) {
    label = '综合';
    score = hybridScore;
  }

  const percent = Math.round(score * 100);
  const vectorPercent = Math.round(vectorScore * 100);
  const keywordPercent = Math.round(keywordScore * 100);
  const hybridPercent = Math.round(hybridScore * 100);

  return {
    label,
    percent,
    description: `匹配依据：${label} ${percent}% · 语义 ${vectorPercent}% · 关键词 ${keywordPercent}% · 综合排序 ${hybridPercent}%`,
  };
}
