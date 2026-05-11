interface Props {
  onOpen: () => void
}

export function AddTodoForm({ onOpen }: Props) {
  return (
    <button
      onClick={onOpen}
      className="w-full rounded-lg border-2 border-dashed border-gray-300 px-4 py-3 text-sm text-gray-400 hover:border-indigo-400 hover:text-indigo-500 transition-colors mb-6 text-left"
    >
      + Add task…
    </button>
  )
}
