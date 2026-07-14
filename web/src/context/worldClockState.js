export function shouldApplyClockRevision(currentRevision, incomingRevision) {
  if (!Number.isInteger(currentRevision) || !Number.isInteger(incomingRevision)) {
    return true;
  }
  return incomingRevision >= currentRevision;
}
