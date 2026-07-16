import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const [dialogSource, eventSource, alertDialogSource, dialogPrimitiveSource] = await Promise.all([
  readFile(new URL('../src/context/DialogContext.jsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/pages/EventList.jsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/components/ui/alert-dialog.jsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/components/ui/dialog.jsx', import.meta.url), 'utf8'),
]);

test('DialogContext delegates modal behavior and semantics to Radix primitives', () => {
  assert.match(dialogSource, /from '@\/components\/ui\/alert-dialog'/);
  assert.match(dialogSource, /from '@\/components\/ui\/dialog'/);
  assert.match(dialogSource, /<AlertDialog\b[^>]*open=/);
  assert.match(dialogSource, /<Dialog\b[^>]*open=/);
  assert.match(dialogSource, /(?:<AlertDialogTitle\b|Title=\{AlertDialogTitle\})/);
  assert.match(dialogSource, /(?:<AlertDialogDescription\b|Description=\{AlertDialogDescription\})/);
  assert.match(dialogSource, /(?:<DialogTitle\b|Title=\{DialogTitle\})/);
  assert.match(dialogSource, /(?:<DialogDescription\b|Description=\{DialogDescription\})/);
  assert.match(dialogSource, /<AlertDialogAction\b/);
  assert.match(dialogSource, /<AlertDialogCancel\b/);
  assert.match(dialogSource, /<DialogClose\b/);
  assert.doesNotMatch(dialogSource, /window\.addEventListener|createPortal/);

  for (const primitiveSource of [alertDialogSource, dialogPrimitiveSource]) {
    assert.match(primitiveSource, /Primitive\.Portal/);
    assert.match(primitiveSource, /archive-portal/);
  }
});

test('DialogContext preserves Promise results while using archive tokens and touch targets', () => {
  assert.match(dialogSource, /const confirm = useCallback\(\(options\) => new Promise/);
  assert.match(dialogSource, /const alert = useCallback\(\(options\) => new Promise/);
  assert.match(dialogSource, /resultRef\.current = true/);
  assert.match(dialogSource, /dismissResult: false/);
  assert.match(dialogSource, /dismissResult: undefined/);
  assert.match(dialogSource, /\bmin-h-11\b|\bh-11\b/);
  assert.doesNotMatch(
    dialogSource,
    /cyber-green|zinc-|emerald-|amber-|red-|bg-black|border-white|#[0-9a-fA-F]{3,8}|rgba\(/,
  );
  assert.doesNotMatch(dialogSource, /rounded-(?:xl|2xl|3xl|full)/);
});

test('DialogContext restores focus for controlled dialogs and settles lifecycle edge cases', () => {
  assert.match(dialogSource, /document\.activeElement/);
  assert.match(dialogSource, /const openerRef = useRef\(null\)/);
  assert.match(dialogSource, /const dialogRef = useRef\(null\)/);
  assert.match(dialogSource, /onCloseAutoFocus=\{handleCloseAutoFocus\}/g);

  const focusLifecycle = dialogSlice(
    dialogSource,
    'const restoreOpenerFocus',
    'const handleOpenChange',
  );
  assert.match(focusLifecycle, /event\.preventDefault\(\)/);
  assert.match(focusLifecycle, /\.isConnected/);
  assert.match(focusLifecycle, /\.focus\(/);
  assert.match(focusLifecycle, /try\s*\{/);

  const lifecycle = dialogSlice(dialogSource, 'export function DialogProvider', 'const value = useMemo');
  assert.match(lifecycle, /previousDialog/);
  assert.match(lifecycle, /previousDialog\.resolve/);
  assert.match(lifecycle, /useEffect\(\(\) => \{/);
  assert.match(lifecycle, /dialogRef\.current = null/);
});

test('Event detail renders every event number with tabular archive mono styling', () => {
  const archiveValue = dialogSlice(eventSource, 'function ArchiveValue', 'function RecordFields');
  const detailItem = dialogSlice(eventSource, 'function DetailItem', 'export default function EventList');

  assert.match(
    archiveValue,
    /typeof value === 'number'[\s\S]{0,180}font-archive-mono[\s\S]{0,80}tabular-nums/,
  );
  assert.match(archiveValue, /<pre className="[^"]*font-archive-mono[^"]*tabular-nums[^"]*"/);
  assert.match(detailItem, /mono \? '[^']*font-archive-mono[^']*tabular-nums[^']*'/);
  assert.match(
    eventSource,
    /<p className="mb-4 font-archive-mono text-sm tabular-nums leading-7 text-foreground">/,
  );
  assert.doesNotMatch(eventSource, /triggerSummaryIsMono/);

  for (const match of eventSource.matchAll(/className="([^"]*\bfont-archive-mono\b[^"]*)"/g)) {
    assert.match(match[1], /\btabular-nums\b/);
  }

  for (const marker of [
    '{filtered.length} records',
    '显示 {filtered.length} / {events.length}',
    '{String(index + 1).padStart',
    '{index}</span>',
  ]) {
    const markerIndex = eventSource.indexOf(marker);
    assert.notEqual(markerIndex, -1, `missing numeric marker: ${marker}`);
    const classStart = eventSource.lastIndexOf('className=', markerIndex);
    const numericMarkup = eventSource.slice(classStart, markerIndex + marker.length);
    assert.match(numericMarkup, /font-archive-mono/);
    assert.match(numericMarkup, /tabular-nums/);
  }

  for (const label of [
    '计划表达式',
    '世界时间触发',
    '现实预计时间',
    '合并漏触发',
    '最后触发',
    '最后更新',
    '创建时间',
  ]) {
    assert.match(
      eventSource,
      new RegExp(`<DetailItem[\\s\\S]{0,80}label="${label}"[\\s\\S]{0,260}\\bmono\\b`),
      `${label} should use mono number styling`,
    );
  }
});

function dialogSlice(source, startMarker, endMarker) {
  return source.slice(source.indexOf(startMarker), source.indexOf(endMarker));
}
