import { User } from 'lucide-react';

export function ChatAvatar({ entity, sizeClass = 'h-10 w-10', extraClass = '' }) {
  const label = entity?.name || entity?.display_name || entity?.username || '';
  return (
    <span className={`${sizeClass} ${extraClass} flex shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted font-archive-serif text-sm font-semibold text-muted-foreground`}>
      {entity?.avatar_url
        ? <img src={entity.avatar_url} alt="" className="h-full w-full object-cover" />
        : label.charAt(0).toUpperCase() || <User className="h-4 w-4" aria-hidden="true" />}
    </span>
  );
}

export default ChatAvatar;
