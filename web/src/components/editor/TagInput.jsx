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
    <div className="flex flex-wrap gap-1.5 items-center p-1.5 min-h-[36px] bg-amber-50/50 rounded border border-amber-300/30 focus-within:border-amber-500 transition-colors">
      {tags.map((tag, idx) => (
        <span
          key={idx}
          className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-mono bg-amber-200/60 text-amber-900 rounded-full"
        >
          {tag}
          <button
            type="button"
            onClick={() => removeTag(idx)}
            className="hover:text-red-600 transition-colors"
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
        className="flex-1 min-w-[120px] px-1 py-0.5 text-sm font-mono text-cyber-ink bg-transparent border-none focus:outline-none"
        placeholder={tags.length === 0 ? placeholder : ''}
      />
    </div>
  );
}
