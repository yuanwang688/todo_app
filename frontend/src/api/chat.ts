import { Proposal } from './proposals'

export interface ChatHistoryItem {
  role: 'user' | 'assistant'
  text: string
  tool_calls: string[]
}

export interface ChatHistory {
  conversation_id: string
  configured: boolean
  messages: ChatHistoryItem[]
  pending_proposals: Proposal[]
}

export type ChatStreamEvent =
  | { type: 'text_delta'; text: string }
  | { type: 'tool_call'; name: string }
  | { type: 'proposal_ready'; proposal_id: string; summary: string; item_count: number }
  | { type: 'error'; message: string }
  | { type: 'done'; reply_text: string; tool_calls: string[]; refusal: boolean; error: string | null }

export async function getChatHistory(): Promise<ChatHistory> {
  const res = await fetch('/api/chat')
  if (!res.ok) throw new Error('Failed to load the assistant.')
  return res.json()
}

/** Consumes the SSE stream from POST /api/chat/messages as an async generator. */
export async function* streamChatMessage(message: string): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch('/api/chat/messages', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(err.detail ?? 'Request failed')
  }
  if (!res.body) throw new Error('No response body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? '' // the last, possibly-incomplete frame stays buffered
    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      yield JSON.parse(line.slice('data: '.length)) as ChatStreamEvent
    }
  }
}
