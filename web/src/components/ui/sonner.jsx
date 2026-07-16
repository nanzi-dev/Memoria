import { Toaster as Sonner, toast } from 'sonner';

import { useArchiveTheme } from '@/archive/ArchiveThemeProvider';

export function Toaster(props) {
  const { theme } = useArchiveTheme();
  return (
    <Sonner
      theme={theme}
      className="archive-portal"
      toastOptions={{
        classNames: {
          toast: 'archive-toast',
          title: 'font-archive-serif text-sm',
          description: 'text-muted-foreground',
          actionButton: 'archive-toast-action',
          cancelButton: 'archive-toast-cancel',
        },
      }}
      {...props}
    />
  );
}

export { toast };
