import { useEffect, useState, FormEvent } from 'react'
import { PlanningPreferences, planningApi } from '../api/planning'

interface Props {
  onClose: () => void
}

const WEEKDAYS: { iso: number; label: string }[] = [
  { iso: 1, label: 'Mon' },
  { iso: 2, label: 'Tue' },
  { iso: 3, label: 'Wed' },
  { iso: 4, label: 'Thu' },
  { iso: 5, label: 'Fri' },
  { iso: 6, label: 'Sat' },
  { iso: 7, label: 'Sun' },
]

// Intl.supportedValuesOf is ES2022; this project's lib target is ES2020.
const supportedTimezones = (): string[] => {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  const zones = intl.supportedValuesOf?.('timeZone') ?? []
  return zones.includes('UTC') ? zones : ['UTC', ...zones]
}

const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone

const inputClass =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500'

/** Capacity and planning policy the assistant plans against — see TRIAGE.md. */
export function PlanningSettingsModal({ onClose }: Props) {
  const [form, setForm] = useState<PlanningPreferences | null>(null)
  const [capacity, setCapacity] = useState('')
  const [horizon, setHorizon] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [timezones] = useState(supportedTimezones)

  useEffect(() => {
    planningApi
      .get()
      .then((prefs) => {
        setForm(prefs)
        setCapacity(String(prefs.daily_capacity_hours))
        setHorizon(String(prefs.urgency_horizon_days))
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const toggleDay = (iso: number) =>
    setForm((f) =>
      f && {
        ...f,
        workdays: f.workdays.includes(iso)
          ? f.workdays.filter((d) => d !== iso)
          : [...f.workdays, iso].sort((a, b) => a - b),
      },
    )

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!form) return
    setSaving(true)
    setError(null)
    try {
      await planningApi.save({
        ...form,
        daily_capacity_hours: Number(capacity),
        urgency_horizon_days: Number(horizon),
      })
      onClose()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const capacityNum = Number(capacity)
  const weeklyCapacity = form ? capacityNum * form.workdays.length : 0
  const invalid =
    !form ||
    form.workdays.length === 0 ||
    capacity === '' ||
    !(capacityNum > 0 && capacityNum <= 24) ||
    horizon === '' ||
    !(Number(horizon) >= 0 && Number(horizon) <= 30)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Planning settings</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none" aria-label="Close">×</button>
        </div>

        {!form ? (
          <p className="px-6 py-8 text-center text-sm text-gray-400">{error ?? 'Loading…'}</p>
        ) : (
          <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
            <p className="text-xs text-gray-500">
              The assistant measures your workload against these when you ask whether you're
              overcommitted or to rebalance your week.
            </p>

            {/* Capacity + horizon */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="capacity" className="block text-xs font-medium text-gray-600 mb-1">Daily capacity (hours)</label>
                <input
                  id="capacity"
                  type="number"
                  value={capacity}
                  onChange={(e) => setCapacity(e.target.value)}
                  min="0.5"
                  max="24"
                  step="0.5"
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="horizon" className="block text-xs font-medium text-gray-600 mb-1">Urgent within (days)</label>
                <input
                  id="horizon"
                  type="number"
                  value={horizon}
                  onChange={(e) => setHorizon(e.target.value)}
                  min="0"
                  max="30"
                  step="1"
                  className={inputClass}
                />
              </div>
            </div>

            {/* Workdays */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Workdays</label>
              <div className="flex gap-1.5">
                {WEEKDAYS.map(({ iso, label }) => {
                  const selected = form.workdays.includes(iso)
                  return (
                    <button
                      key={iso}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => toggleDay(iso)}
                      className={`flex-1 rounded-lg border px-2 py-1.5 text-sm font-medium transition-colors ${
                        selected
                          ? 'border-indigo-300 bg-indigo-100 text-indigo-800'
                          : 'border-gray-200 bg-white text-gray-500 hover:bg-gray-50'
                      }`}
                    >
                      {label}
                    </button>
                  )
                })}
              </div>
              <p className="mt-1 text-xs text-gray-400">
                {form.workdays.length === 0
                  ? 'Pick at least one workday.'
                  : `Other days count as 0h. ${weeklyCapacity}h capacity per week.`}
              </p>
            </div>

            {/* Timezone */}
            <div>
              <label htmlFor="timezone" className="block text-xs font-medium text-gray-600 mb-1">Timezone</label>
              <select
                id="timezone"
                value={form.timezone}
                onChange={(e) => setForm({ ...form, timezone: e.target.value })}
                className={inputClass}
              >
                {(timezones.includes(form.timezone) ? timezones : [form.timezone, ...timezones]).map((tz) => (
                  <option key={tz} value={tz}>{tz}</option>
                ))}
              </select>
              {form.timezone !== browserTimezone && timezones.includes(browserTimezone) && (
                <button
                  type="button"
                  onClick={() => setForm({ ...form, timezone: browserTimezone })}
                  className="mt-1 text-xs text-indigo-600 hover:underline"
                >
                  Use this device's timezone ({browserTimezone})
                </button>
              )}
            </div>

            {/* Notes */}
            <div>
              <label htmlFor="notes" className="block text-xs font-medium text-gray-600 mb-1">Planning notes</label>
              <textarea
                id="notes"
                value={form.notes ?? ''}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="e.g. Never schedule Work tasks on weekends."
                rows={3}
                maxLength={2000}
                className={`${inputClass} resize-none`}
              />
              <p className="mt-1 text-xs text-gray-400">The assistant follows these when it proposes changes.</p>
            </div>

            {error && <p className="text-sm text-red-500">{error}</p>}

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
                disabled={saving || invalid}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
