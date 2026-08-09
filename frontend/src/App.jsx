import { Routes, Route } from 'react-router-dom'

import AppShell from '@/components/AppShell'
import Placeholder from '@/pages/Placeholder'

/**
 * Route table. Phase 0 ships one placeholder route; Phase 3 adds /login,
 * /dashboard, /generate, /reports, /reports/:id, /chat, /users, /profile and
 * /settings behind a ProtectedRoute wrapper.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Placeholder />} />
        <Route path="*" element={<Placeholder notFound />} />
      </Route>
    </Routes>
  )
}
