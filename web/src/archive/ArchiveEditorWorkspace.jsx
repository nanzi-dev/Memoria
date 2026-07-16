import { cn } from '@/lib/utils';

export default function ArchiveEditorWorkspace({
  indexLabel,
  title,
  description,
  directory,
  editor,
  summary,
  mobileAction,
  notice,
  className,
}) {
  return (
    <div className={cn('min-w-0 overflow-x-clip px-3 py-4 sm:px-5 sm:py-6', className)}>
      {notice}
      <div className="mb-4 border-b border-border pb-4">
        {indexLabel && (
          <p className="font-archive-mono text-[11px] uppercase text-muted-foreground">
            {indexLabel}
          </p>
        )}
        <h1 className="mt-1 font-archive-serif text-xl font-semibold text-foreground sm:text-2xl">
          {title}
        </h1>
        {description && (
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        )}
      </div>

      <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(190px,230px)_minmax(0,1fr)_minmax(220px,280px)] xl:grid-cols-[minmax(220px,280px)_minmax(0,1fr)_minmax(240px,320px)]">
        <aside className="min-w-0 border border-border bg-card lg:sticky lg:top-20">
          {directory}
        </aside>

        <section className="min-w-0 border border-border bg-card shadow-sm">
          {editor}
        </section>

        <aside className="min-w-0 border border-border bg-card lg:sticky lg:top-20">
          {summary}
        </aside>
      </div>

      {mobileAction && (
        <div className="sticky bottom-0 z-20 -mx-3 mt-4 border-t border-border bg-background/95 px-3 py-3 backdrop-blur lg:hidden">
          {mobileAction}
        </div>
      )}
    </div>
  );
}
