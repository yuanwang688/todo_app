import { useEffect, useRef, useState, FormEvent } from 'react'
import { ChatHistoryItem, getChatHistory, streamChatMessage } from '../api/chat'
import { Proposal, proposalsApi } from '../api/proposals'
import { ProposalCard } from './ProposalCard'

interface Props {
  open: boolean
  onClose: () => void
  onTodosChanged: () => void
}

interface DisplayMessage {
  role: 'user' | 'assistant'
  text: string
  toolCalls: string[]
  pending?: boolean
}

const TOOL_LABELS: Record<string, string> = {
  search_todos: 'searched your tasks',
  get_todo_details: 'looked up a task',
  get_workload_summary: 'checked your workload',
}

function toolChipLabel(name: string): string {
  return TOOL_LABELS[name] ?? name
}

export function ChatPanel({ open, onClose, onTodosChanged }: Props) {
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open || loaded) return
    getChatHistory()
      .then((history) => {
        setConfigured(history.configured)
        setMessages(
          history.messages
            .filter((m) => m.text || m.tool_calls.length > 0)
            .map((m: ChatHistoryItem) => ({ role: m.role, text: m.text, toolCalls: m.tool_calls })),
        )
        setProposals(history.pending_proposals)
        setLoaded(true)
      })
      .catch((err) => setLoadError(err.message ?? 'Failed to load the assistant.'))
  }, [open, loaded])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, proposals, sending])

  function updateProposal(updated: Proposal) {
    setProposals((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending) return

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', text, toolCalls: [] }])
    setMessages((prev) => [...prev, { role: 'assistant', text: '', toolCalls: [], pending: true }])
    setSending(true)

    try {
      for await (const event of streamChatMessage(text)) {
        if (event.type === 'proposal_ready') {
          proposalsApi.get(event.proposal_id).then((p) => setProposals((prev) => [...prev, p]))
          continue
        }
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?.role !== 'assistant' || !last.pending) return prev

          if (event.type === 'text_delta') {
            next[next.length - 1] = { ...last, text: last.text + event.text }
          } else if (event.type === 'tool_call') {
            if (!last.toolCalls.includes(event.name)) {
              next[next.length - 1] = { ...last, toolCalls: [...last.toolCalls, event.name] }
            } else {
              return prev
            }
          } else if (event.type === 'error') {
            next[next.length - 1] = { ...last, text: event.message, pending: false }
          } else if (event.type === 'done') {
            next[next.length - 1] = {
              ...last,
              text: event.error ? last.text || 'The assistant hit an error. Try again.' : event.reply_text,
              toolCalls: event.tool_calls,
              pending: false,
            }
          }
          return next
        })
      }
    } catch (err) {
      setMessages((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (last?.role === 'assistant' && last.pending) {
          next[next.length - 1] = {
            ...last,
            text: err instanceof Error ? err.message : 'Something went wrong.',
            pending: false,
          }
        }
        return next
      })
    } finally {
      setSending(false)
    }
  }

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/20 sm:hidden" onClick={onClose} />}
      <div
        className={`fixed right-0 top-0 z-50 flex h-full w-full flex-col bg-white shadow-xl transition-transform duration-200 sm:w-96 sm:border-l sm:border-gray-200 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-900">Assistant</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none" aria-label="Close assistant">
            ×
          </button>
        </div>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {loadError && <p className="text-sm text-red-600">{loadError}</p>}

          {configured === false && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              The assistant isn't set up on this server yet.
            </p>
          )}

          {loaded && messages.length === 0 && (
            <p className="text-sm text-gray-400">
              Ask about your tasks — "what's overdue?", "what fits in 30 minutes?", "am I overcommitted this week?"
            </p>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                  m.role === 'user' ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-800'
                }`}
              >
                {m.toolCalls.length > 0 && (
                  <div className="mb-1 flex flex-wrap gap-1">
                    {m.toolCalls.map((name, j) => (
                      <span
                        key={j}
                        className="inline-flex items-center rounded-full bg-white/70 px-2 py-0.5 text-[11px] font-medium text-gray-500"
                      >
                        🔍 {toolChipLabel(name)}
                      </span>
                    ))}
                  </div>
                )}
                {m.text ? (
                  <span className="whitespace-pre-wrap">{m.text}</span>
                ) : m.pending ? (
                  <span className="text-gray-400">…</span>
                ) : null}
              </div>
            </div>
          ))}

          {proposals.map((p) => (
            <ProposalCard key={p.id} proposal={p} onChange={updateProposal} onTodosChanged={onTodosChanged} />
          ))}
        </div>

        <form onSubmit={handleSubmit} className="border-t px-3 py-3">
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={configured === false ? 'Assistant not configured' : 'Ask about your tasks…'}
              disabled={sending || configured === false}
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-400"
            />
            <button
              type="submit"
              disabled={sending || !input.trim() || configured === false}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Send
            </button>
          </div>
        </form>
      </div>
    </>
  )
}
