import test from 'node:test';
import assert from 'node:assert/strict';

import { getKnowledgeSourceMatch } from '../src/pages/knowledgePreviewScore.js';

test('knowledge preview displays keyword evidence when lexical retrieval rescued a hit', () => {
  const match = getKnowledgeSourceMatch({
    similarity: 0,
    vector_similarity: 0,
    keyword_score: 0.91,
    hybrid_score: 0.89,
  });

  assert.equal(match.label, '关键词');
  assert.equal(match.percent, 91);
  assert.match(match.description, /语义 0%/);
  assert.match(match.description, /关键词 91%/);
});

test('knowledge preview keeps semantic similarity for vector-led hits', () => {
  const match = getKnowledgeSourceMatch({
    similarity: 0.884,
    keyword_score: 0.2,
    hybrid_score: 0.37,
  });

  assert.equal(match.label, '语义');
  assert.equal(match.percent, 88);
});

test('knowledge preview falls back to a bounded hybrid score when channel scores are absent', () => {
  const match = getKnowledgeSourceMatch({
    hybrid_score: 1.4,
  });

  assert.equal(match.label, '综合');
  assert.equal(match.percent, 100);
});
