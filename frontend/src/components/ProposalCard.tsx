import { useState } from 'react'
import { ApplyItemResult, Proposal, proposalsApi } from '../api/proposals'
import { ChangeRow } from './ChangeRow'

const PROPOSAL_STATUS_BADGE: Record<string, { label: string; className: string }> = {
  pending: { label: 'Awaiting your review', className: 'bg-indigo-100 text-indigo-700' },
  applied: { label: 'Applied', className: 'bg-green-100 text-green-700' },
  rejected: { label: 'Rejected', className: 'bg-gray-100 text-gray-500' },
  expired: { label: 'Expired', className: 'bg-gray-100 text-gray-500' },
  undone: { label: 'Undone', className: 'bg-gray-100 text-gray-500' },
}

interface Props {
  proposal: Proposal
  onChange: (updated: Proposal) => void
  onTodosChanged: () => void
}

export function ProposalCard({ proposal, onChange, onTodosChanged }: Props) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(proposal.items.filter((i) => i.status === 'pending').map((i) => i.id)),
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [blockedResults, setBlockedResults] = useState<Map<string, ApplyItemResult>>(new Map())

  const isPending = proposal.status === 'pending'
  const isApplied = proposal.status === 'applied'
  const badge = PROPOSAL_STATUS_BADGE[proposal.status]

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleApply() {
    if (selected.size === 0) return
    setBusy(true)
    setError(null)
    try {
      const result = await proposalsApi.apply(proposal.id, [...selected])
      if (result.proposal_status === 'applied') {
        setBlockedResults(new Map())
        onChange(await proposalsApi.get(proposal.id))
        onTodosChanged()
        return
      }
      // Blocked: nothing committed. Surface why, and deselect the blockers
      // so the next click retries cleanly with just the clean items.
      const byId = new Map(result.items.map((i) => [i.item_id, i]))
      setBlockedResults(byId)
      setSelected((prev) => new Set([...prev].filter((id) => byId.get(id)?.status === 'applied' || !byId.has(id))))
      setError('Some selected items couldn’t be applied — see details below, then try again.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to apply.')
    } finally {
      setBusy(false)
    }
  }

  async function handleReject() {
    setBusy(true)
    setError(null)
    try {
      onChange(await proposalsApi.reject(proposal.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reject.')
    } finally {
      setBusy(false)
    }
  }

  async function handleUndo() {
    setBusy(true)
    setError(null)
    try {
      onChange(await proposalsApi.undo(proposal.id))
      onTodosChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to undo.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/40 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-gray-800">{proposal.summary}</span>
        {badge && (
          <span className={`shrink-0 inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${badge.className}`}>
            {badge.label}
          </span>
        )}
      </div>

      <ul className="space-y-2">
        {proposal.items.map((item) => (
          <ChangeRow
            key={item.id}
            item={item}
            interactive={isPending}
            selected={selected.has(item.id)}
            onToggle={() => toggle(item.id)}
            busy={busy}
            blocked={blockedResults.get(item.id)}
          />
        ))}
      </ul>

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      {isPending && (
        <div className="mt-3 flex gap-2">
          <button
            onClick={handleApply}
            disabled={busy || selected.size === 0}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Apply selected ({selected.size})
          </button>
          <button
            onClick={handleReject}
            disabled={busy}
            className="rounded-md bg-white px-3 py-1.5 text-xs font-medium text-gray-600 ring-1 ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Reject all
          </button>
        </div>
      )}

      {isApplied && (
        <div className="mt-3">
          <button
            onClick={handleUndo}
            disabled={busy}
            className="rounded-md bg-white px-3 py-1.5 text-xs font-medium text-gray-600 ring-1 ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Undo
          </button>
        </div>
      )}
    </div>
  )
}
