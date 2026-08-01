export function ChatSummaryRow({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-3 py-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-archive-mono text-sm text-foreground tabular-nums">{value}</dd>
    </div>
  );
}

export default ChatSummaryRow;
