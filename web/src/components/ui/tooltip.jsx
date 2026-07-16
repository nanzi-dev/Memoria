import { forwardRef } from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';

import { cn } from '@/lib/utils';

export function TooltipProvider({ delayDuration = 300, ...props }) {
  return <TooltipPrimitive.Provider delayDuration={delayDuration} {...props} />;
}

export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = forwardRef(function TooltipContent(
  { className, sideOffset = 6, ...props },
  ref,
) {
  return (
    <TooltipPrimitive.Portal>
      <div className="archive-portal">
        <TooltipPrimitive.Content
          ref={ref}
          sideOffset={sideOffset}
          className={cn(
            'z-[1200] max-w-64 rounded border border-border bg-popover px-2.5 py-1.5 text-xs leading-5 text-popover-foreground shadow-lg',
            className,
          )}
          {...props}
        />
      </div>
    </TooltipPrimitive.Portal>
  );
});
