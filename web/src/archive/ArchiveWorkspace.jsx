import FadeContent from '@/components/FadeContent';
import { cn } from '@/lib/utils';

function ArchiveMetric({ icon: Icon, label, value, note }) {
  return (
    <div className="min-w-0 border-l border-border pl-3 sm:pl-4">
      <dt className="flex items-center gap-2 text-xs text-muted-foreground">
        {Icon && <Icon className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />}
        <span>{label}</span>
      </dt>
      <dd className="mt-1 flex min-w-0 items-baseline gap-2">
        <span className="font-archive-mono text-lg font-semibold tabular-nums text-foreground">
          {value}
        </span>
        {note && <span className="min-w-0 break-words text-[11px] text-muted-foreground">{note}</span>}
      </dd>
    </div>
  );
}

export default function ArchiveWorkspace({
  indexLabel,
  title,
  description,
  stats,
  mobileAction,
  notice,
  directory,
  detail,
  className,
}) {
  return (
    <div className={cn('mx-auto min-w-0 max-w-[1800px] px-3 py-5 sm:px-5 lg:py-6', className)}>
      {notice}

      <FadeContent className="border-b border-border pb-5">
        <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 max-w-3xl">
            <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">
              {indexLabel}
            </p>
            <h1 className="mt-1 font-archive-serif text-2xl font-semibold text-foreground sm:text-3xl">
              {title}
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              {description}
            </p>
          </div>
          {mobileAction && <div className="shrink-0 lg:hidden">{mobileAction}</div>}
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-y-4 sm:grid-cols-4">
          {stats.map(stat => <ArchiveMetric key={stat.label} {...stat} />)}
        </dl>
      </FadeContent>

      <div className="mt-5 grid min-w-0 items-start gap-5 lg:grid-cols-[minmax(300px,380px)_minmax(0,1fr)]">
        <aside className="min-w-0 overflow-hidden rounded-md border border-border bg-card">
          {directory}
        </aside>
        <div className="min-w-0 border-t border-border pt-5 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
          {detail}
        </div>
      </div>
    </div>
  );
}
