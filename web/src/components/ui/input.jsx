import { forwardRef } from 'react';

import { cn } from '@/lib/utils';

export const Input = forwardRef(function Input({ className, type, ...props }, ref) {
  return (
    <input
      type={type}
      className={cn(
        'flex h-11 w-full rounded-md border border-input bg-background/72 px-3 py-2 text-base text-foreground shadow-sm transition-colors duration-200 file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-45 sm:text-sm',
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
