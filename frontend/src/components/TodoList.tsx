import { Todo, TodoUpdate } from '../api/todos'
import { TodoItem } from './TodoItem'

interface Props {
  todos: Todo[]
  onUpdate: (id: string, data: TodoUpdate) => Promise<void>
  onDelete: (id: string) => Promise<void>
  onEdit: (todo: Todo) => void
}

export function TodoList({ todos, onUpdate, onDelete, onEdit }: Props) {
  if (todos.length === 0) {
    return (
      <p className="text-center text-sm text-gray-400 py-8">No tasks here.</p>
    )
  }

  return (
    <ul className="flex flex-col gap-2">
      {todos.map((todo) => (
        <TodoItem key={todo.id} todo={todo} onUpdate={onUpdate} onDelete={onDelete} onEdit={onEdit} />
      ))}
    </ul>
  )
}
