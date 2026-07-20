function clampUnitScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return 0;
  return Math.min(1, Math.max(0, score));
}

export function getKnowledgeSourceMatch(source = {}) {
  const vectorScore = clampUnitScore(source.vector_similarity ?? source.similarity);
  const keywordScore = clampUnitScore(source.keyword_score);
  const hybridScore = clampUnitScore(source.hybrid_score);
  const hasHybridScore = source.hybrid_score !== null
    && source.hybrid_score !== undefined
    && Number.isFinite(Number(source.hybrid_score));

  let label = '综合排序';
  let score = hybridScore;
  if (!hasHybridScore && keywordScore > vectorScore) {
    label = '关键词';
    score = keywordScore;
  } else if (!hasHybridScore) {
    label = '语义';
    score = vectorScore;
  }

  const percent = Math.round(score * 100);
  const vectorPercent = Math.round(vectorScore * 100);
  const keywordPercent = Math.round(keywordScore * 100);
  const hybridPercent = Math.round(hybridScore * 100);

  return {
    label,
    percent,
    description: `综合排序 ${hybridPercent}% · 语义 ${vectorPercent}% · 关键词 ${keywordPercent}%`,
  };
}
