export interface Todo {
  id: string
  user_id: string
  title: string
  description: string | null
  completed: boolean
  category: string | null
  target_date: string | null   // "YYYY-MM-DD"
  start_date: string | null
  end_date: string | null
  estimated_effort: number | null
  created_at: string
  updated_at: string
}

export type TodoCreate = {
  title: string
  description?: string | null
  category?: string | null
  target_date?: string | null
  start_date?: string | null
  end_date?: string | null
  estimated_effort?: number | null
}

export type TodoUpdate = {
  title?: string
  description?: string | null
  completed?: boolean
  category?: string | null
  target_date?: string | null
  start_date?: string | null
  end_date?: string | null
  estimated_effort?: number | null
}

const BASE = '/api/todos'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail ?? 'Request failed')
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const todosApi = {
  list: () => request<Todo[]>(BASE),

  create: (data: TodoCreate) =>
    request<Todo>(BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  update: (id: string, data: TodoUpdate) =>
    request<Todo>(`${BASE}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  delete: (id: string) =>
    request<void>(`${BASE}/${id}`, { method: 'DELETE' }),
}
