import { useQuery } from '@tanstack/react-query'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/**
 * Phase 0 placeholder. Its one job is to prove the scaffold is wired end to
 * end: router -> TanStack Query -> backend. Phase 3 deletes it.
 */
export default function Placeholder({ notFound = false }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/`)
      if (!response.ok) throw new Error(`Backend returned ${response.status}`)
      return response.json()
    },
  })

  return (
    <div className="mx-auto max-w-xl space-y-6">
      {notFound && (
        <p className="text-sm text-console-muted">
          No route matches this URL yet.
        </p>
      )}

      <div>
        <h1 className="text-2xl font-semibold">Scaffold running</h1>
        <p className="mt-1 text-sm text-console-muted">
          Phase 0. Routing, data layer and styling are in place; pages arrive in
          Phase 3.
        </p>
      </div>

      <div className="rounded-lg border border-console-border bg-console-surface p-4">
        <h2 className="text-sm font-medium text-console-muted">Backend status</h2>
        {isPending && <p className="mt-2 text-sm">Checking…</p>}
        {isError && (
          <p className="mt-2 text-sm text-red-400">
            Unreachable at {API_BASE_URL} — {error.message}
          </p>
        )}
        {data && (
          <p className="mt-2 text-sm">
            <span className="text-console-accent">{data.status}</span> · {data.app} ·{' '}
            {data.environment}
          </p>
        )}
      </div>
    </div>
  )
}
