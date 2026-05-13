import { Todo, TodoUpdate } from '../api/todos'

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

export function TodoItem({ todo, onUpdate, onDelete, onEdit, dueTag }: Props) {
  return (
    <li className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
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
          {(dueTag || todo.category || todo.target_date || todo.start_date || todo.estimated_effort != null) && (
            <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
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
