const MAX_REPLY_BUBBLES = 6;
const MAX_SHORT_SEGMENT_LENGTH = 48;

function splitSentences(value) {
  const matches = value.match(/[^。！？!?…\n]+(?:[。！？!?]+|…{1,2}|$)/g);
  return (matches || [value]).map(part => part.trim()).filter(Boolean);
}

export function splitAssistantReply(content) {
  const source = String(content ?? '').trim();
  if (!source) return [];

  const lines = source.split(/\n+/).map(line => line.trim()).filter(Boolean);
  const segments = lines.flatMap(splitSentences);

  if (
    segments.length < 2
    || segments.length > MAX_REPLY_BUBBLES
    || segments.some(segment => segment.length > MAX_SHORT_SEGMENT_LENGTH)
  ) {
    return [source];
  }

  return segments;
}
