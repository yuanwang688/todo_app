import { useState } from 'react'
import { AddTodoForm } from './components/AddTodoForm'
import { TodoList } from './components/TodoList'
import { useTodos, FilterStatus } from './hooks/useTodos'

const FILTERS: { label: string; value: FilterStatus }[] = [
  { label: 'All', value: 'all' },
  { label: 'Active', value: 'active' },
  { label: 'Completed', value: 'completed' },
]

function App() {
  const [filter, setFilter] = useState<FilterStatus>('all')
  const { todos, loading, error, add, update, remove } = useTodos(filter)

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="mx-auto max-w-lg">
        <h1 className="text-3xl font-bold text-gray-900 mb-8 text-center">Todo App</h1>

        <AddTodoForm onAdd={add} />

        <div className="flex gap-1 mb-4">
          {FILTERS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                filter === value
                  ? 'bg-indigo-600 text-white'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {error && (
          <p className="text-sm text-red-500 mb-4 text-center">{error}</p>
        )}

        {loading ? (
          <p className="text-center text-sm text-gray-400 py-8">Loading…</p>
        ) : (
          <TodoList todos={todos} onUpdate={update} onDelete={remove} />
        )}
      </div>
    </div>
  )
}

export default App
