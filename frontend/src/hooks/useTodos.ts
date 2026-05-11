import { useState, useEffect, useCallback } from 'react'
import { todosApi, Todo, TodoCreate, TodoUpdate } from '../api/todos'

export type FilterStatus = 'all' | 'active' | 'completed'

export function useTodos(filter: FilterStatus) {
  const [todos, setTodos] = useState<Todo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await todosApi.list(filter === 'all' ? undefined : filter)
      setTodos(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load todos')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { load() }, [load])

  const add = async (data: TodoCreate) => {
    const todo = await todosApi.create(data)
    setTodos((prev) => [...prev, todo])
  }

  const update = async (id: string, data: TodoUpdate) => {
    const updated = await todosApi.update(id, data)
    setTodos((prev) => prev.map((t) => (t.id === id ? updated : t)))
  }

  const remove = async (id: string) => {
    await todosApi.delete(id)
    setTodos((prev) => prev.filter((t) => t.id !== id))
  }

  return { todos, loading, error, add, update, remove }
}
