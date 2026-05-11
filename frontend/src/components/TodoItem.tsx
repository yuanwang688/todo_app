import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import { Todo, TodoUpdate } from '../api/todos'

interface Props {
  todo: Todo
  onUpdate: (id: string, data: TodoUpdate) => Promise<void>
  onDelete: (id: string) => Promise<void>
}

export function TodoItem({ todo, onUpdate, onDelete }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(todo.title)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const commitEdit = async () => {
    const trimmed = draft.trim()
    if (trimmed && trimmed !== todo.title) {
      await onUpdate(todo.id, { title: trimmed })
    } else {
      setDraft(todo.title)
    }
    setEditing(false)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') commitEdit()
    if (e.key === 'Escape') { setDraft(todo.title); setEditing(false) }
  }

  return (
    <li className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
      <input
        type="checkbox"
        checked={todo.completed}
        onChange={(e) => onUpdate(todo.id, { completed: e.target.checked })}
        className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
      />

      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={handleKeyDown}
          className="flex-1 rounded border border-indigo-400 px-2 py-0.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      ) : (
        <span
          onDoubleClick={() => { setDraft(todo.title); setEditing(true) }}
          className={`flex-1 text-sm cursor-pointer select-none ${todo.completed ? 'line-through text-gray-400' : 'text-gray-800'}`}
          title="Double-click to edit"
        >
          {todo.title}
        </span>
      )}

      <button
        onClick={() => onDelete(todo.id)}
        className="text-gray-400 hover:text-red-500 transition-colors text-lg leading-none"
        aria-label="Delete todo"
      >
        ×
      </button>
    </li>
  )
}
