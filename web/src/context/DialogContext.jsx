import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { AlertTriangle, CheckCircle2, Info, Trash2, X } from 'lucide-react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button, buttonVariants } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

const DialogContext = createContext(null);

const VARIANT = {
  info: {
    Icon: Info,
    icon: 'border-primary/30 bg-primary/10 text-primary',
    action: 'default',
  },
  success: {
    Icon: CheckCircle2,
    icon: 'border-primary/30 bg-primary/10 text-primary',
    action: 'default',
  },
  warning: {
    Icon: AlertTriangle,
    icon: 'border-border bg-secondary text-secondary-foreground',
    action: 'secondary',
  },
  danger: {
    Icon: Trash2,
    icon: 'border-destructive/35 bg-destructive/10 text-destructive',
    action: 'destructive',
  },
};

function normalizeOptions(options, fallbackTitle) {
  if (typeof options === 'string') return { title: fallbackTitle, message: options };
  return { title: fallbackTitle, ...options };
}

function DialogMessage({
  dialog,
  variant,
  Header,
  Title,
  Description,
  closeControl,
  footer,
}) {
  const Icon = variant.Icon;

  return (
    <>
      <div className="flex min-w-0 items-start gap-4 p-5 pr-16 sm:p-6 sm:pr-16">
        <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-md border ${variant.icon}`}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
        <Header className="min-w-0 flex-1">
          <Title className="break-words">{dialog.title}</Title>
          <Description className="whitespace-pre-line break-words">
            {dialog.message}
          </Description>
        </Header>
        {closeControl}
      </div>
      <div className="border-t border-border bg-muted/25 p-4 sm:px-6">
        {footer}
      </div>
    </>
  );
}

export function DialogProvider({ children }) {
  const [dialog, setDialog] = useState(null);
  const resultRef = useRef(undefined);
  const openerRef = useRef(null);
  const dialogRef = useRef(null);
  const mountedRef = useRef(true);

  const close = useCallback((result) => {
    const currentDialog = dialogRef.current;
    if (!currentDialog) return;

    dialogRef.current = null;
    resultRef.current = undefined;
    if (mountedRef.current) setDialog(null);

    if (!currentDialog.settled) {
      currentDialog.settled = true;
      try {
        currentDialog.resolve(result);
      } catch {
        // Promise settlement must not break dialog teardown.
      }
    }
  }, []);

  const restoreOpenerFocus = useCallback(() => {
    const opener = openerRef.current;
    openerRef.current = null;
    if (!opener?.isConnected || typeof opener.focus !== 'function') return;

    try {
      opener.focus({ preventScroll: true });
    } catch {
      try {
        opener.focus();
      } catch {
        // The opener may become disconnected while the dialog is closing.
      }
    }
  }, []);

  const presentDialog = useCallback((nextDialog) => {
    if (!mountedRef.current) {
      nextDialog.settled = true;
      try {
        nextDialog.resolve(nextDialog.dismissResult);
      } catch {
        // A retained context callback may be invoked after provider teardown.
      }
      return;
    }

    const previousDialog = dialogRef.current;
    if (!previousDialog && typeof document !== 'undefined') {
      try {
        openerRef.current = document.activeElement;
      } catch {
        openerRef.current = null;
      }
    }

    dialogRef.current = nextDialog;
    resultRef.current = nextDialog.dismissResult;

    if (previousDialog && !previousDialog.settled) {
      previousDialog.settled = true;
      try {
        previousDialog.resolve(previousDialog.dismissResult);
      } catch {
        // Replacing a dialog must not prevent the next one from opening.
      }
    }

    setDialog(nextDialog);
  }, []);

  const confirm = useCallback((options) => new Promise((resolve) => {
    presentDialog({
      type: 'confirm',
      variant: 'warning',
      confirmText: '确认',
      cancelText: '取消',
      ...normalizeOptions(options, '确认操作'),
      dismissResult: false,
      settled: false,
      resolve,
    });
  }), [presentDialog]);

  const alert = useCallback((options) => new Promise((resolve) => {
    presentDialog({
      type: 'alert',
      variant: 'info',
      confirmText: '知道了',
      ...normalizeOptions(options, '提示'),
      dismissResult: undefined,
      settled: false,
      resolve,
    });
  }), [presentDialog]);

  const handleCloseAutoFocus = useCallback((event) => {
    event.preventDefault();
    if (dialogRef.current) return;
    restoreOpenerFocus();
  }, [restoreOpenerFocus]);

  const handleOpenChange = useCallback((open, type) => {
    if (!open && dialogRef.current?.type === type) close(resultRef.current);
  }, [close]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const currentDialog = dialogRef.current;
      dialogRef.current = null;
      resultRef.current = undefined;

      if (currentDialog && !currentDialog.settled) {
        currentDialog.settled = true;
        try {
          currentDialog.resolve(currentDialog.dismissResult);
        } catch {
          // Provider teardown must not surface errors from pending callers.
        }
      }

      restoreOpenerFocus();
    };
  }, [restoreOpenerFocus]);

  const value = useMemo(() => ({ alert, confirm }), [alert, confirm]);
  const variant = dialog ? VARIANT[dialog.variant] || VARIANT.info : VARIANT.info;

  return (
    <DialogContext.Provider value={value}>
      {children}

      <AlertDialog
        open={dialog?.type === 'confirm'}
        onOpenChange={open => handleOpenChange(open, 'confirm')}
      >
        {dialog?.type === 'confirm' && (
          <AlertDialogContent
            className="max-w-md gap-0 overflow-hidden rounded-md p-0 motion-reduce:transition-none"
            onPointerDownOutside={() => close(false)}
            onCloseAutoFocus={handleCloseAutoFocus}
          >
            <DialogMessage
              dialog={dialog}
              variant={variant}
              Header={AlertDialogHeader}
              Title={AlertDialogTitle}
              Description={AlertDialogDescription}
              closeControl={(
                <AlertDialogCancel
                  className="absolute right-3 top-3 h-11 min-h-11 w-11 min-w-11 border-0 bg-transparent p-0 text-muted-foreground shadow-none hover:bg-accent hover:text-accent-foreground"
                  aria-label="关闭"
                  title="关闭"
                >
                  <X aria-hidden="true" />
                </AlertDialogCancel>
              )}
              footer={(
                <AlertDialogFooter>
                  <AlertDialogCancel className="min-h-11">
                    {dialog.cancelText}
                  </AlertDialogCancel>
                  <AlertDialogAction
                    className={buttonVariants({
                      variant: variant.action,
                      size: 'lg',
                      className: 'min-h-11',
                    })}
                    onClick={() => {
                      resultRef.current = true;
                    }}
                    autoFocus
                  >
                    {dialog.confirmText}
                  </AlertDialogAction>
                </AlertDialogFooter>
              )}
            />
          </AlertDialogContent>
        )}
      </AlertDialog>

      <Dialog
        open={dialog?.type === 'alert'}
        onOpenChange={open => handleOpenChange(open, 'alert')}
      >
        {dialog?.type === 'alert' && (
          <DialogContent
            className="max-w-md gap-0 overflow-hidden rounded-md p-0 motion-reduce:transition-none"
            showClose={false}
            onCloseAutoFocus={handleCloseAutoFocus}
          >
            <DialogMessage
              dialog={dialog}
              variant={variant}
              Header={DialogHeader}
              Title={DialogTitle}
              Description={DialogDescription}
              closeControl={(
                <DialogClose
                  className="absolute right-3 top-3 inline-flex h-11 min-h-11 w-11 min-w-11 items-center justify-center rounded-md text-muted-foreground transition-colors duration-200 hover:bg-accent hover:text-accent-foreground focus:outline-none focus:ring-2 focus:ring-ring motion-reduce:transition-none"
                  aria-label="关闭"
                  title="关闭"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </DialogClose>
              )}
              footer={(
                <DialogFooter>
                  <DialogClose asChild>
                    <Button
                      type="button"
                      variant={variant.action}
                      size="lg"
                      onClick={() => {
                        resultRef.current = undefined;
                      }}
                      autoFocus
                    >
                      {dialog.confirmText}
                    </Button>
                  </DialogClose>
                </DialogFooter>
              )}
            />
          </DialogContent>
        )}
      </Dialog>
    </DialogContext.Provider>
  );
}

export function useDialog() {
  const context = useContext(DialogContext);
  if (!context) throw new Error('useDialog must be used within DialogProvider');
  return context;
}
