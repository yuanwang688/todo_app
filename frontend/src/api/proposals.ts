export type ProposalItemStatus = 'pending' | 'applied' | 'skipped' | 'stale' | 'invalid' | 'undone'
export type ProposalStatus = 'pending' | 'applied' | 'rejected' | 'expired' | 'undone'

export interface ProposalItem {
  id: string
  op: 'create' | 'update' | 'delete'
  todo_id: string | null
  todo_title: string | null
  /** update: {field: {from, to}}. create: {field: value}. delete: {}. */
  changes: Record<string, unknown>
  rationale: string
  quadrant: string | null
  status: ProposalItemStatus
}

export interface Proposal {
  id: string
  summary: string
  status: ProposalStatus
  created_at: string
  applied_at: string | null
  items: ProposalItem[]
}

export interface ApplyItemResult {
  item_id: string
  status: 'applied' | 'skipped' | 'stale' | 'invalid'
  detail: string | null
}

export interface ApplyResult {
  proposal_status: ProposalStatus
  items: ApplyItemResult[]
}

const BASE = '/api/proposals'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail ?? 'Request failed')
  }
  return res.json()
}

export const proposalsApi = {
  get: (id: string) => request<Proposal>(`${BASE}/${id}`),

  apply: (id: string, itemIds: string[]) =>
    request<ApplyResult>(`${BASE}/${id}/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_ids: itemIds }),
    }),

  reject: (id: string) => request<Proposal>(`${BASE}/${id}/reject`, { method: 'POST' }),

  undo: (id: string) => request<Proposal>(`${BASE}/${id}/undo`, { method: 'POST' }),
}
