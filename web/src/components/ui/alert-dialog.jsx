import { forwardRef } from 'react';
import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog';

import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export const AlertDialog = AlertDialogPrimitive.Root;
export const AlertDialogTrigger = AlertDialogPrimitive.Trigger;
export const AlertDialogPortal = AlertDialogPrimitive.Portal;

export const AlertDialogOverlay = forwardRef(function AlertDialogOverlay(
  { className, ...props },
  ref,
) {
  return (
    <AlertDialogPrimitive.Overlay
      ref={ref}
      className={cn(
        'fixed inset-0 z-[1000] bg-black/72 backdrop-blur-sm transition-opacity duration-200 data-[state=closed]:opacity-0 data-[state=open]:opacity-100',
        className,
      )}
      {...props}
    />
  );
});
export const AlertDialogContent = forwardRef(function AlertDialogContent(
  { className, ...props },
  ref,
) {
  return (
    <AlertDialogPrimitive.Portal>
      <div className="archive-portal">
        <AlertDialogOverlay />
        <AlertDialogPrimitive.Content
          ref={ref}
          className={cn(
            'fixed left-1/2 top-1/2 z-[1001] grid w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 rounded-lg border border-border bg-background p-5 text-foreground shadow-2xl transition duration-200 data-[state=closed]:scale-95 data-[state=closed]:opacity-0 data-[state=open]:scale-100 data-[state=open]:opacity-100 sm:p-6',
            className,
          )}
          {...props}
        />
      </div>
    </AlertDialogPrimitive.Portal>
  );
});

export function AlertDialogHeader({ className, ...props }) {
  return <div className={cn('flex flex-col gap-2 text-left', className)} {...props} />;
}

export function AlertDialogFooter({ className, ...props }) {
  return (
    <div
      className={cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
      {...props}
    />
  );
}

export const AlertDialogTitle = forwardRef(function AlertDialogTitle(
  { className, ...props },
  ref,
) {
  return (
    <AlertDialogPrimitive.Title
      ref={ref}
      className={cn('font-archive-serif text-xl font-semibold text-foreground', className)}
      {...props}
    />
  );
});

export const AlertDialogDescription = forwardRef(function AlertDialogDescription(
  { className, ...props },
  ref,
) {
  return (
    <AlertDialogPrimitive.Description
      ref={ref}
      className={cn('text-sm leading-6 text-muted-foreground', className)}
      {...props}
    />
  );
});

export const AlertDialogAction = forwardRef(function AlertDialogAction(
  { className, ...props },
  ref,
) {
  return (
    <AlertDialogPrimitive.Action
      ref={ref}
      className={cn(buttonVariants(), className)}
      {...props}
    />
  );
});

export const AlertDialogCancel = forwardRef(function AlertDialogCancel(
  { className, ...props },
  ref,
) {
  return (
    <AlertDialogPrimitive.Cancel
      ref={ref}
      className={cn(buttonVariants({ variant: 'outline' }), className)}
      {...props}
    />
  );
});
