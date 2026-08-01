import { AlertTriangle, X } from 'lucide-react';
import { Button } from '../ui/button';

export function ChatErrorNotice({ error, onDismiss }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-destructive/35 bg-destructive/10 px-3 py-2 text-xs text-destructive">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 break-words">{error}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="-my-2 -mr-2 shrink-0 text-destructive"
        onClick={onDismiss}
        aria-label="关闭错误提示"
      >
        <X aria-hidden="true" />
      </Button>
    </div>
  );
}

export default ChatErrorNotice;
