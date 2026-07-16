import { forwardRef } from 'react';
import * as SheetPrimitive from '@radix-ui/react-dialog';
import { cva } from 'class-variance-authority';
import { X } from 'lucide-react';

import { cn } from '@/lib/utils';

export const Sheet = SheetPrimitive.Root;
export const SheetTrigger = SheetPrimitive.Trigger;
export const SheetClose = SheetPrimitive.Close;
export const SheetPortal = SheetPrimitive.Portal;

export const SheetOverlay = forwardRef(function SheetOverlay(
  { className, ...props },
  ref,
) {
  return (
    <SheetPrimitive.Overlay
      ref={ref}
      className={cn(
        'fixed inset-0 z-[1000] bg-black/68 backdrop-blur-sm transition-opacity duration-200 data-[state=closed]:opacity-0 data-[state=open]:opacity-100',
        className,
      )}
      {...props}
    />
  );
});

const sheetVariants = cva(
  'fixed z-[1001] flex gap-4 border-border bg-background p-5 text-foreground shadow-2xl transition-transform duration-200 ease-out',
  {
    variants: {
      side: {
        top: 'inset-x-0 top-0 border-b data-[state=closed]:-translate-y-full data-[state=open]:translate-y-0',
        bottom: 'inset-x-0 bottom-0 border-t data-[state=closed]:translate-y-full data-[state=open]:translate-y-0',
        left: 'inset-y-0 left-0 h-full w-[min(88vw,360px)] border-r data-[state=closed]:-translate-x-full data-[state=open]:translate-x-0',
        right: 'inset-y-0 right-0 h-full w-[min(88vw,360px)] border-l data-[state=closed]:translate-x-full data-[state=open]:translate-x-0',
      },
    },
    defaultVariants: {
      side: 'right',
    },
  },
);

export const SheetContent = forwardRef(function SheetContent(
  { side = 'right', className, children, ...props },
  ref,
) {
  return (
    <SheetPrimitive.Portal>
      <div className="archive-portal">
        <SheetOverlay />
        <SheetPrimitive.Content
          ref={ref}
          className={cn(sheetVariants({ side }), className)}
          {...props}
        >
          {children}
          <SheetPrimitive.Close
            className="absolute right-3 top-3 inline-flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors duration-200 hover:bg-accent hover:text-accent-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </SheetPrimitive.Close>
        </SheetPrimitive.Content>
      </div>
    </SheetPrimitive.Portal>
  );
});

export function SheetHeader({ className, ...props }) {
  return <div className={cn('flex flex-col gap-1.5 text-left', className)} {...props} />;
}

export function SheetFooter({ className, ...props }) {
  return <div className={cn('mt-auto flex flex-col gap-2', className)} {...props} />;
}

export const SheetTitle = forwardRef(function SheetTitle({ className, ...props }, ref) {
  return (
    <SheetPrimitive.Title
      ref={ref}
      className={cn('font-archive-serif text-xl font-semibold text-foreground', className)}
      {...props}
    />
  );
});

export const SheetDescription = forwardRef(function SheetDescription(
  { className, ...props },
  ref,
) {
  return (
    <SheetPrimitive.Description
      ref={ref}
      className={cn('text-sm leading-6 text-muted-foreground', className)}
      {...props}
    />
  );
});

