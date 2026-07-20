import test from 'node:test';
import assert from 'node:assert/strict';

import { getKnowledgeSourceMatch } from '../src/pages/knowledgePreviewScore.js';

test('knowledge preview displays the hybrid ranking score for lexical retrieval hits', () => {
  const match = getKnowledgeSourceMatch({
    similarity: 0,
    vector_similarity: 0,
    keyword_score: 0.91,
    hybrid_score: 0.89,
  });

  assert.equal(match.label, '综合排序');
  assert.equal(match.percent, 89);
  assert.match(match.description, /语义 0%/);
  assert.match(match.description, /关键词 91%/);
});

test('knowledge preview displays the hybrid ranking score for vector-led hits', () => {
  const match = getKnowledgeSourceMatch({
    similarity: 0.884,
    keyword_score: 0.2,
    hybrid_score: 0.37,
  });

  assert.equal(match.label, '综合排序');
  assert.equal(match.percent, 37);
});

test('knowledge preview bounds the hybrid ranking score', () => {
  const match = getKnowledgeSourceMatch({
    hybrid_score: 1.4,
  });

  assert.equal(match.label, '综合排序');
  assert.equal(match.percent, 100);
});

test('knowledge preview falls back to channel scores for legacy responses', () => {
  const match = getKnowledgeSourceMatch({
    similarity: 0,
    keyword_score: 0.82,
  });

  assert.equal(match.label, '关键词');
  assert.equal(match.percent, 82);
});
