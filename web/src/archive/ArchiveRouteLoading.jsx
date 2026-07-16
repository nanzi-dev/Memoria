import { Archive, Loader2 } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';

export default function ArchiveRouteLoading() {
  return (
    <div
      className="archive-route-loading flex min-h-[calc(100dvh-4rem)] items-center justify-center px-5 py-12"
      role="status"
      aria-live="polite"
    >
      <div className="w-full max-w-3xl rounded-lg border border-border bg-card/70 p-5 shadow-lg sm:p-7">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-md border border-primary/30 bg-primary/10 text-primary">
            <Archive className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 font-archive-serif text-base text-foreground">
              <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
              正在调取档案
            </div>
            <p className="mt-1 text-xs text-muted-foreground">正在准备页面与叙事资料</p>
          </div>
        </div>
        <div className="mt-6 space-y-3" aria-hidden="true">
          <Skeleton className="h-3 w-2/5" />
          <Skeleton className="h-24 w-full" />
          <div className="grid gap-3 sm:grid-cols-3">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        </div>
        <span className="sr-only">正在加载页面</span>
      </div>
    </div>
  );
}
