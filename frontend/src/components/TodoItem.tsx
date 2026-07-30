import { Todo, TodoUpdate, Importance, IMPORTANCE_LABELS } from '../api/todos'

interface Props {
  todo: Todo
  onUpdate: (id: string, data: TodoUpdate) => Promise<void>
  onDelete: (id: string) => Promise<void>
  onEdit: (todo: Todo) => void
  dueTag?: string
}

function fmtDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

const IMPORTANCE_BADGE: Record<Importance, string> = {
  1: 'bg-gray-100 text-gray-600',
  2: 'bg-sky-50 text-sky-700',
  3: 'bg-rose-50 text-rose-700',
}

export function TodoItem({ todo, onUpdate, onDelete, onEdit, dueTag }: Props) {
  return (
    <li className={`rounded-lg border px-4 py-3 shadow-sm ${todo.is_focus ? 'border-amber-400 bg-amber-50 ring-1 ring-amber-300' : 'border-gray-200 bg-white'}`}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={todo.completed}
          onChange={(e) => onUpdate(todo.id, { completed: e.target.checked })}
          className="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
        />

        <div className="flex-1 min-w-0">
          <span className={`text-sm font-medium ${todo.completed ? 'line-through text-gray-400' : 'text-gray-800'}`}>
            {todo.title}
          </span>

          {/* Metadata row */}
          {(dueTag || todo.category || todo.target_date || todo.start_date ||
            todo.estimated_effort != null || todo.importance != null || todo.locked) && (
            <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
              {todo.importance != null && (
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 font-medium ${IMPORTANCE_BADGE[todo.importance]}`}>
                  {IMPORTANCE_LABELS[todo.importance]}
                </span>
              )}
              {todo.locked && (
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600">
                  🔒 Locked
                </span>
              )}
              {dueTag && (
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 font-semibold ${
                  dueTag === 'Due Today'
                    ? 'bg-red-100 text-red-700'
                    : 'bg-amber-100 text-amber-700'
                }`}>
                  {dueTag}
                </span>
              )}
              {todo.category && (
                <span className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 font-medium text-indigo-700">
                  {todo.category}
                </span>
              )}
              {todo.target_date && (
                <span>🎯 {fmtDate(todo.target_date)}</span>
              )}
              {todo.start_date && todo.end_date && (
                <span>📅 {fmtDate(todo.start_date)} – {fmtDate(todo.end_date)}</span>
              )}
              {todo.estimated_effort != null && (
                <span>⏱ {todo.estimated_effort}h</span>
              )}
            </div>
          )}

          {todo.description && (
            <p className="mt-1 text-xs text-gray-500 line-clamp-2">{todo.description}</p>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => onUpdate(todo.id, { locked: !todo.locked })}
            className={`rounded p-1 transition-colors ${todo.locked ? 'text-slate-600 hover:bg-slate-100' : 'text-gray-300 hover:text-slate-500 hover:bg-slate-50'}`}
            aria-label={todo.locked ? 'Unlock task' : 'Lock task'}
            title={todo.locked ? 'Locked — the assistant cannot change this task' : 'Lock this task so the assistant cannot change it'}
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              {todo.locked ? (
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 11V7a4 4 0 018 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z" />
              )}
            </svg>
          </button>
          <button
            onClick={() => onUpdate(todo.id, { is_focus: !todo.is_focus })}
            className={`rounded p-1 transition-colors ${todo.is_focus ? 'text-amber-500 hover:text-amber-600 hover:bg-amber-100' : 'text-gray-400 hover:text-amber-500 hover:bg-amber-50'}`}
            aria-label={todo.is_focus ? 'Remove focus' : 'Set as focus'}
            title={todo.is_focus ? 'Remove focus' : 'Set as focus'}
          >
            <svg className="h-3.5 w-3.5" fill={todo.is_focus ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
            </svg>
          </button>
          <button
            onClick={() => onEdit(todo)}
            className="rounded p-1 text-gray-400 hover:text-indigo-500 hover:bg-indigo-50 transition-colors"
            aria-label="Edit todo"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536M9 13l6.586-6.586a2 2 0 112.828 2.828L11.828 15.828a2 2 0 01-1.414.586H9v-2a2 2 0 01.586-1.414z" />
            </svg>
          </button>
          <button
            onClick={() => onDelete(todo.id)}
            className="rounded p-1 text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors text-lg leading-none"
            aria-label="Delete todo"
          >
            ×
          </button>
        </div>
      </div>
    </li>
  )
}
