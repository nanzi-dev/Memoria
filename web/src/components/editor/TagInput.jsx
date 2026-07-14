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
    <div className="flex min-h-[44px] flex-wrap items-center gap-1.5 rounded-md border border-cyber-green/15 bg-black/25 p-1.5 transition-colors focus-within:border-cyber-green/50 focus-within:ring-2 focus-within:ring-cyber-green/[0.08]">
      {tags.map((tag, idx) => (
        <span
          key={idx}
          className="inline-flex min-h-8 items-center gap-1 rounded-md border border-cyber-green/15 bg-cyber-green/[0.07] px-2 text-xs font-mono text-cyber-green/80"
        >
          {tag}
          <button
            type="button"
            onClick={() => removeTag(idx)}
            className="flex h-7 w-7 items-center justify-center rounded text-cyber-green/45 transition-colors hover:bg-red-400/10 hover:text-red-300"
            aria-label={`移除 ${tag}`}
          >
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        className="min-h-8 min-w-[120px] flex-1 border-none bg-transparent px-1 text-sm font-mono text-zinc-200 outline-none placeholder:text-cyber-green/20"
        placeholder={tags.length === 0 ? placeholder : ''}
      />
    </div>
  );
}
