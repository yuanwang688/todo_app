/** Planning preferences (Phase D) — what the assistant plans capacity against. */
export interface PlanningPreferences {
  daily_capacity_hours: number
  /** ISO weekdays, 1 = Mon … 7 = Sun. */
  workdays: number[]
  urgency_horizon_days: number
  /** IANA timezone name — decides what "today" means for the assistant. */
  timezone: string
  notes: string | null
}

const BASE = '/api/planning-preferences'

async function request<T>(init?: RequestInit): Promise<T> {
  const res = await fetch(BASE, init)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }))
    // 422s carry FastAPI's list of field errors rather than a string.
    const detail = Array.isArray(err.detail)
      ? err.detail.map((e: { msg: string }) => e.msg).join('; ')
      : err.detail
    throw new Error(detail ?? 'Request failed')
  }
  return res.json()
}

export const planningApi = {
  get: () => request<PlanningPreferences>(),

  save: (prefs: PlanningPreferences) =>
    request<PlanningPreferences>({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prefs),
    }),
}
