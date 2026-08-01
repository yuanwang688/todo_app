import { ProposalItem } from '../api/proposals'
import { Importance, IMPORTANCE_LABELS } from '../api/todos'

const FIELD_LABELS: Record<string, string> = {
  title: 'Title',
  description: 'Description',
  category: 'Category',
  target_date: 'Due date',
  start_date: 'Start date',
  end_date: 'End date',
  estimated_effort: 'Estimate',
  importance: 'Importance',
  is_focus: 'Focus',
}

const QUADRANT_LABELS: Record<string, string> = {
  Q1: 'Do',
  Q2: 'Schedule',
  Q3: 'Minimise',
  Q4: 'Defer',
}

function fmtDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function formatValue(field: string, value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (field === 'importance') return IMPORTANCE_LABELS[value as Importance] ?? String(value)
  if (field === 'estimated_effort') return `${value}h`
  if (field === 'is_focus') return value ? 'Yes' : 'No'
  if (field === 'target_date' || field === 'start_date' || field === 'end_date') return fmtDate(String(value))
  return String(value)
}

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  applied: { label: 'Applied', className: 'bg-green-100 text-green-700' },
  skipped: { label: 'Not selected', className: 'bg-gray-100 text-gray-500' },
  undone: { label: 'Undone', className: 'bg-gray-100 text-gray-500' },
  stale: { label: 'Stale', className: 'bg-amber-100 text-amber-700' },
  invalid: { label: 'Blocked', className: 'bg-red-100 text-red-700' },
}

interface Props {
  item: ProposalItem
  interactive: boolean
  selected: boolean
  onToggle: () => void
  busy: boolean
  blocked?: { status: string; detail: string | null }
}

export function ChangeRow({ item, interactive, selected, onToggle, busy, blocked }: Props) {
  const title = item.todo_title ?? (item.op === 'create' ? String(item.changes.title ?? 'New task') : 'Unknown task')
  const finalStatus = !interactive ? STATUS_BADGE[item.status] : undefined

  return (
    <li className="rounded-md border border-gray-200 bg-white px-3 py-2">
      <div className="flex items-start gap-2">
        {interactive ? (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            disabled={busy}
            className="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer disabled:cursor-not-allowed"
          />
        ) : (
          <span className="mt-0.5 shrink-0 text-sm">
            {item.status === 'applied' ? '✓' : item.status === 'undone' ? '↺' : '·'}
          </span>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">
              {item.op}
            </span>
            <span className="text-sm font-medium text-gray-800 truncate">{title}</span>
            {item.quadrant && (
              <span className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700">
                {QUADRANT_LABELS[item.quadrant] ?? item.quadrant}
              </span>
            )}
            {finalStatus && (
              <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${finalStatus.className}`}>
                {finalStatus.label}
              </span>
            )}
          </div>

          {item.op === 'delete' ? (
            <p className="mt-0.5 text-xs text-gray-500">This task will be deleted.</p>
          ) : (
            <dl className="mt-0.5 space-y-0.5 text-xs text-gray-600">
              {Object.entries(item.changes)
                .filter(([field]) => field !== 'title' || item.op !== 'create')
                .map(([field, value]) => (
                  <div key={field} className="flex gap-1">
                    <dt className="font-medium text-gray-500">{FIELD_LABELS[field] ?? field}:</dt>
                    <dd>
                      {item.op === 'update' && value && typeof value === 'object' && 'to' in (value as object) ? (
                        <>
                          {formatValue(field, (value as { from: unknown; to: unknown }).from)}
                          {' → '}
                          {formatValue(field, (value as { from: unknown; to: unknown }).to)}
                        </>
                      ) : (
                        formatValue(field, value)
                      )}
                    </dd>
                  </div>
                ))}
            </dl>
          )}

          <p className="mt-1 text-xs italic text-gray-500">{item.rationale}</p>

          {blocked && (
            <p className="mt-1 text-xs font-medium text-amber-700">
              ⚠ {blocked.status === 'stale' ? 'Stale' : 'Blocked'} — {blocked.detail ?? 'this item could not be applied'}
            </p>
          )}
        </div>
      </div>
    </li>
  )
}
