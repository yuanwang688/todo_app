import { useState } from 'react'
import { useAuth, AuthUser } from './hooks/useAuth'
import { useTodos } from './hooks/useTodos'
import { Todo, TodoCreate, TodoUpdate } from './api/todos'
import { Header } from './components/Header'
import { LoginButton } from './components/LoginButton'
import { AddTodoForm } from './components/AddTodoForm'
import { TodoList } from './components/TodoList'
import { TodoModal } from './components/TodoModal'

// ─── date helpers ────────────────────────────────────────────────────────────

function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function getWeekBounds(d: Date): { start: Date; end: Date } {
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day   // shift to Monday
  const start = new Date(d)
  start.setDate(d.getDate() + diff)
  start.setHours(0, 0, 0, 0)
  const end = new Date(start)
  end.setDate(start.getDate() + 6)
  return { start, end }
}

function fmtDay(d: Date) {
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
}

function fmtWeek(start: Date, end: Date) {
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
  const s = start.toLocaleDateString(undefined, opts)
  const e = end.toLocaleDateString(undefined, { ...opts, year: 'numeric' })
  return `${s} – ${e}`
}

// ─── filter logic ────────────────────────────────────────────────────────────

type TabValue = 'all' | 'active' | 'completed' | 'daily' | 'weekly'

function filterTodos(todos: Todo[], tab: TabValue, viewDate: Date): Todo[] {
  if (tab === 'active') return todos.filter((t) => !t.completed)
  if (tab === 'completed') return todos.filter((t) => t.completed)

  if (tab === 'daily') {
    const d = toDateStr(viewDate)
    return todos.filter(
      (t) =>
        t.target_date === d ||
        (t.start_date && t.end_date && t.start_date <= d && t.end_date >= d),
    )
  }

  if (tab === 'weekly') {
    const { start, end } = getWeekBounds(viewDate)
    const ws = toDateStr(start)
    const we = toDateStr(end)
    return todos.filter(
      (t) =>
        (t.target_date && t.target_date >= ws && t.target_date <= we) ||
        (t.start_date && t.end_date && t.start_date <= we && t.end_date >= ws),
    )
  }

  return todos
}

// ─── components ──────────────────────────────────────────────────────────────

const TABS: { label: string; value: TabValue }[] = [
  { label: 'All', value: 'all' },
  { label: 'Active', value: 'active' },
  { label: 'Completed', value: 'completed' },
  { label: 'Daily', value: 'daily' },
  { label: 'Weekly', value: 'weekly' },
]

interface TodoAppProps {
  user: AuthUser
  onLogout: () => void
}

function TodoApp({ user, onLogout }: TodoAppProps) {
  const [tab, setTab] = useState<TabValue>('all')
  const [viewDate, setViewDate] = useState(new Date())
  const [modalOpen, setModalOpen] = useState(false)
  const [editingTodo, setEditingTodo] = useState<Todo | undefined>(undefined)
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const [dueFilter, setDueFilter] = useState<'today' | 'week' | null>(null)

  const { todos, loading, error, add, update, remove } = useTodos()

  const openCreate = () => { setEditingTodo(undefined); setModalOpen(true) }
  const openEdit = (todo: Todo) => { setEditingTodo(todo); setModalOpen(true) }
  const closeModal = () => setModalOpen(false)

  const handleSubmit = async (data: TodoCreate | TodoUpdate) => {
    if (editingTodo) {
      await update(editingTodo.id, data as TodoUpdate)
    } else {
      await add(data as TodoCreate)
    }
  }

  const shiftDay = (n: number) => {
    const d = new Date(viewDate)
    d.setDate(d.getDate() + n)
    setViewDate(d)
  }

  const shiftWeek = (n: number) => {
    const d = new Date(viewDate)
    d.setDate(d.getDate() + n * 7)
    setViewDate(d)
  }

  const { start: weekStart, end: weekEnd } = getWeekBounds(viewDate)

  const categories = [...new Set(todos.map((t) => t.category).filter((c): c is string => Boolean(c)))].sort()
  const todayStr = toDateStr(new Date())
  const { start: curWeekStart, end: curWeekEnd } = getWeekBounds(new Date())
  const curWeekStartStr = toDateStr(curWeekStart)
  const curWeekEndStr = toDateStr(curWeekEnd)

  const visible = filterTodos(todos, tab, viewDate)
    .filter((t) => !categoryFilter || t.category === categoryFilter)
    .filter((t) => {
      if (dueFilter === 'today') return t.target_date === todayStr
      if (dueFilter === 'week') return Boolean(t.target_date) && t.target_date! >= curWeekStartStr && t.target_date! <= curWeekEndStr
      return true
    })

  const getDueTag = (todo: Todo): string | undefined => {
    if (tab === 'daily') {
      if (todo.target_date === toDateStr(viewDate)) return 'Due Today'
    }
    if (tab === 'weekly') {
      const ws = toDateStr(weekStart)
      const we = toDateStr(weekEnd)
      if (todo.target_date && todo.target_date >= ws && todo.target_date <= we) return 'Due This Week'
    }
    return undefined
  }

  return (
    <div className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="mx-auto max-w-2xl">
        <Header user={user} onLogout={onLogout} />

        <AddTodoForm onOpen={openCreate} />

        {/* Tab bar */}
        <div className="flex gap-1 mb-4 flex-wrap">
          {TABS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setTab(value)}
              className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                tab === value
                  ? 'bg-indigo-600 text-white'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Date navigator for Daily / Weekly */}
        {tab === 'daily' && (
          <div className="flex items-center justify-between mb-4 text-sm">
            <button onClick={() => shiftDay(-1)} className="px-2 py-1 rounded hover:bg-gray-200 transition-colors">‹ Prev</button>
            <span className="font-medium text-gray-700">{fmtDay(viewDate)}</span>
            <button onClick={() => shiftDay(1)} className="px-2 py-1 rounded hover:bg-gray-200 transition-colors">Next ›</button>
          </div>
        )}
        {tab === 'weekly' && (
          <div className="flex items-center justify-between mb-4 text-sm">
            <button onClick={() => shiftWeek(-1)} className="px-2 py-1 rounded hover:bg-gray-200 transition-colors">‹ Prev</button>
            <span className="font-medium text-gray-700">{fmtWeek(weekStart, weekEnd)}</span>
            <button onClick={() => shiftWeek(1)} className="px-2 py-1 rounded hover:bg-gray-200 transition-colors">Next ›</button>
          </div>
        )}

        {/* Filter bar */}
        {(categories.length > 0 || true) && (
          <div className="flex flex-wrap gap-2 mb-4">
            <button
              onClick={() => setDueFilter(dueFilter === 'today' ? null : 'today')}
              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors ${
                dueFilter === 'today'
                  ? 'bg-red-100 text-red-700 ring-1 ring-red-300'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              Due Today
            </button>
            <button
              onClick={() => setDueFilter(dueFilter === 'week' ? null : 'week')}
              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors ${
                dueFilter === 'week'
                  ? 'bg-amber-100 text-amber-700 ring-1 ring-amber-300'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              Due This Week
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategoryFilter(categoryFilter === cat ? null : cat)}
                className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                  categoryFilter === cat
                    ? 'bg-indigo-100 text-indigo-700 ring-1 ring-indigo-300'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}

        {error && <p className="text-sm text-red-500 mb-4 text-center">{error}</p>}

        {loading ? (
          <p className="text-center text-sm text-gray-400 py-8">Loading…</p>
        ) : (
          <TodoList todos={visible} onUpdate={update} onDelete={remove} onEdit={openEdit} getDueTag={getDueTag} />
        )}
      </div>

      {modalOpen && (
        <TodoModal
          initial={editingTodo}
          onSubmit={handleSubmit}
          onClose={closeModal}
        />
      )}
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
