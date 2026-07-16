import { useState, useRef } from 'react';
import { X } from 'lucide-react';

export default function TagInput({ tags = [], onChange, placeholder = 'Add item...' }) {
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef(null);

  function handleKeyDown(e) {
    if (e.key === 'Enter' && inputValue.trim()) {
      e.preventDefault();
      onChange([...tags, inputValue.trim()]);
      setInputValue('');
    }
    if (e.key === 'Backspace' && !inputValue && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  }

  function removeTag(index) {
    onChange(tags.filter((_, i) => i !== index));
  }

  return (
    <div className="flex min-h-11 min-w-0 flex-wrap items-center gap-1.5 rounded-md border border-input bg-background p-1.5 transition-colors focus-within:ring-2 focus-within:ring-ring">
      {tags.map((tag, idx) => (
        <span
          key={idx}
          className="inline-flex min-w-0 items-center gap-1 rounded-md border border-primary/20 bg-primary/10 py-0.5 pl-2 font-archive-serif text-sm text-foreground"
        >
          <span className="max-w-full break-words">{tag}</span>
          <button
            type="button"
            onClick={() => removeTag(idx)}
            className="-my-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/5 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`移除 ${tag}`}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        className="min-h-9 min-w-[120px] flex-1 border-none bg-transparent px-2 font-archive-serif text-base text-foreground outline-none placeholder:text-muted-foreground"
        placeholder={tags.length === 0 ? placeholder : ''}
      />
    </div>
  );
}
