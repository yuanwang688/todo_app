import { useState, useEffect, FormEvent } from 'react'
import { Todo, TodoCreate, TodoUpdate } from '../api/todos'

interface Props {
  initial?: Todo
  onSubmit: (data: TodoCreate | TodoUpdate) => Promise<void>
  onClose: () => void
}

interface FormState {
  title: string
  category: string
  description: string
  target_date: string
  start_date: string
  end_date: string
  estimated_effort: string
}

function fromTodo(todo?: Todo): FormState {
  return {
    title: todo?.title ?? '',
    category: todo?.category ?? '',
    description: todo?.description ?? '',
    target_date: todo?.target_date ?? '',
    start_date: todo?.start_date ?? '',
    end_date: todo?.end_date ?? '',
    estimated_effort: todo?.estimated_effort != null ? String(todo.estimated_effort) : '',
  }
}

function toPayload(f: FormState): TodoCreate | TodoUpdate {
  return {
    title: f.title.trim(),
    category: f.category.trim() || null,
    description: f.description.trim() || null,
    target_date: f.target_date || null,
    start_date: f.start_date || null,
    end_date: f.end_date || null,
    estimated_effort: f.estimated_effort !== '' ? Number(f.estimated_effort) : null,
  }
}

export function TodoModal({ initial, onSubmit, onClose }: Props) {
  const [form, setForm] = useState<FormState>(fromTodo(initial))
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setForm(fromTodo(initial))
  }, [initial])

  const set = (field: keyof FormState) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [field]: e.target.value }))

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!form.title.trim()) return
    setSubmitting(true)
    try {
      await onSubmit(toPayload(form))
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">
            {initial ? 'Edit task' : 'New task'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Title <span className="text-red-500">*</span></label>
            <input
              type="text"
              value={form.title}
              onChange={set('title')}
              placeholder="Task title"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              autoFocus
            />
          </div>

          {/* Category + Effort */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Category</label>
              <input
                type="text"
                value={form.category}
                onChange={set('category')}
                placeholder="e.g. Work, Personal"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Estimated effort (hours)</label>
              <input
                type="number"
                value={form.estimated_effort}
                onChange={set('estimated_effort')}
                placeholder="e.g. 2.5"
                min="0"
                step="0.5"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={set('description')}
              placeholder="Optional notes…"
              rows={2}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-none"
            />
          </div>

          {/* Target date */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Target date</label>
            <input
              type="date"
              value={form.target_date}
              onChange={set('target_date')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          {/* Start + End date */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Start date</label>
              <input
                type="date"
                value={form.start_date}
                onChange={set('start_date')}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">End date</label>
              <input
                type="date"
                value={form.end_date}
                onChange={set('end_date')}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !form.title.trim()}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {initial ? 'Save' : 'Add task'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
