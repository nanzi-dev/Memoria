import {
  AlertTriangle,
  Loader2,
  Mic,
  RotateCw,
  Send,
  Square,
  X,
} from 'lucide-react';
import { Button } from '../ui/button';
import { Textarea } from '../ui/textarea';

function SpeechRecorderButton({ status, supported, disabled, onStart, onStop }) {
  const isRecording = status === 'recording';
  const isTranscribing = status === 'transcribing';
  const label = isRecording
    ? '停止录音并转写'
    : isTranscribing
      ? '正在转写录音'
      : supported
        ? '开始语音输入'
        : '当前浏览器不支持录音';

  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      onClick={isRecording ? onStop : onStart}
      disabled={disabled || isTranscribing || (!supported && !isRecording)}
      className={`shrink-0 ${isRecording ? 'border-destructive/60 bg-destructive/10 text-destructive' : 'text-muted-foreground'}`}
      aria-label={label}
      title={label}
    >
      {isTranscribing ? <Loader2 size={16} className="animate-spin" />
        : isRecording ? <Square size={15} fill="currentColor" />
          : <Mic size={17} />}
    </Button>
  );
}

function SpeechErrorNotice({ error, onDismiss, onRetry }) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-2 flex items-center gap-2 rounded-md border border-destructive/35 bg-destructive/10 px-3 py-2 text-xs leading-5 text-destructive">
      <AlertTriangle size={13} className="shrink-0" />
      <span className="min-w-0 flex-1 break-words">{error}</span>
      <Button type="button" variant="ghost" size="icon" onClick={onRetry} className="shrink-0 text-destructive" aria-label="重试语音输入" title="重试语音输入">
        <RotateCw size={14} />
      </Button>
      <Button type="button" variant="ghost" size="icon" onClick={onDismiss} className="shrink-0 text-destructive" aria-label="关闭语音错误">
        <X size={15} />
      </Button>
    </div>
  );
}

export function ChatComposer({
  input,
  inputRef,
  onInputChange,
  onKeyDown,
  singleReadOnly,
  sending,
  sendingMulti,
  speechStatus,
  speechError,
  isRecordingSupported,
  onStartRecording,
  onStopRecording,
  onDismissSpeechError,
  onSend,
}) {
  const disabled = singleReadOnly || sending || sendingMulti;
  return (
    <div className="shrink-0 border-t border-border bg-card px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:px-4">
      <SpeechErrorNotice error={speechError} onDismiss={onDismissSpeechError} onRetry={onStartRecording} />
      <div className="flex items-end gap-2">
        <SpeechRecorderButton
          status={speechStatus}
          supported={isRecordingSupported}
          disabled={disabled}
          onStart={onStartRecording}
          onStop={onStopRecording}
        />
        <Textarea
          ref={inputRef}
          value={input}
          onChange={event => onInputChange(event.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={singleReadOnly ? '角色已离线，只能查看历史' : '输入消息'}
          disabled={disabled}
          className="max-h-28 min-h-11 flex-1 resize-none"
        />
        <Button
          type="button"
          size="icon"
          onClick={() => onSend()}
          disabled={disabled || !input.trim()}
          aria-label="发送消息"
        >
          <Send aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}

export default ChatComposer;
