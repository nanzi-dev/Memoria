import { forwardRef } from 'react';

import { cn } from '@/lib/utils';

export const Textarea = forwardRef(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      className={cn(
        'flex min-h-24 w-full resize-y rounded-md border border-input bg-background/72 px-3 py-2 text-base leading-6 text-foreground shadow-sm transition-colors duration-200 placeholder:text-muted-foreground/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-45 sm:text-sm',
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});

