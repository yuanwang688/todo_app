import { AuthUser } from '../hooks/useAuth'

interface Props {
  user: AuthUser
  onLogout: () => void
}

export function Header({ user, onLogout }: Props) {
  return (
    <div className="flex items-center justify-between mb-8">
      <h1 className="text-3xl font-bold text-gray-900">Todo App</h1>
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-600">{user.name ?? user.email}</span>
        <button
          onClick={onLogout}
          className="rounded-md px-3 py-1.5 text-sm font-medium text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
        >
          Sign out
        </button>
      </div>
    </div>
  )
}
