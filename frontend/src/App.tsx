import { useState } from 'react'
import { useAuth, AuthUser } from './hooks/useAuth'
import { useTodos, FilterStatus } from './hooks/useTodos'
import { Header } from './components/Header'
import { LoginButton } from './components/LoginButton'
import { AddTodoForm } from './components/AddTodoForm'
import { TodoList } from './components/TodoList'

const FILTERS: { label: string; value: FilterStatus }[] = [
  { label: 'All', value: 'all' },
  { label: 'Active', value: 'active' },
  { label: 'Completed', value: 'completed' },
]

interface TodoAppProps {
  user: AuthUser
  onLogout: () => void
}

function TodoApp({ user, onLogout }: TodoAppProps) {
  const [filter, setFilter] = useState<FilterStatus>('all')
  const { todos, loading, error, add, update, remove } = useTodos(filter)

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="mx-auto max-w-lg">
        <Header user={user} onLogout={onLogout} />

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

        {error && <p className="text-sm text-red-500 mb-4 text-center">{error}</p>}

        {loading ? (
          <p className="text-center text-sm text-gray-400 py-8">Loading…</p>
        ) : (
          <TodoList todos={todos} onUpdate={update} onDelete={remove} />
        )}
      </div>
    </div>
  )
}

function LoginPage() {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center gap-6">
      <h1 className="text-4xl font-bold text-gray-900">Todo App</h1>
      <p className="text-gray-500 text-sm">Sign in to manage your todos</p>
      <LoginButton />
    </div>
  )
}

function App() {
  const { user, loading, logout } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-400 text-sm">Loading…</p>
      </div>
    )
  }

  if (!user) return <LoginPage />

  return <TodoApp key={user.id} user={user} onLogout={logout} />
}

export default App
