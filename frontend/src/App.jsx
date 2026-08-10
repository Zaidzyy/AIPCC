import { Navigate, Route, Routes } from "react-router-dom";

import { IntroSequence } from "@/components/common/IntroSequence";
import { AppShell } from "@/components/layout/AppShell";
import { Alerts } from "@/pages/Alerts";
import { Audit } from "@/pages/Audit";
import { Chat } from "@/pages/Chat";
import { Dashboard } from "@/pages/Dashboard";
import { Generate } from "@/pages/Generate";
import { Login } from "@/pages/Login";
import { NotFound } from "@/pages/NotFound";
import { Profile } from "@/pages/Profile";
import { ReportDetail } from "@/pages/ReportDetail";
import { Reports } from "@/pages/Reports";
import { Settings } from "@/pages/Settings";
import { SharedReport } from "@/pages/SharedReport";
import { Users } from "@/pages/Users";
import { AdminRoute, ProtectedRoute } from "@/routes/ProtectedRoute";

/**
 * Every page is a route. The prototype rendered all of them stacked inside
 * App.jsx with no router at all — see CLAUDE.md > Hard rules #4.
 */
export default function App() {
  return (
    <>
      {/* Overlays the app rather than delaying it, so the first paint is the
          real UI even while the intro is on screen. */}
      <IntroSequence />

      <Routes>
        <Route path="/login" element={<Login />} />

        {/* Outside the protected tree *and* outside the app shell. A share
            link grants read of one report and nothing else, so the page it
            lands on offers no navigation to anything else either. */}
        <Route path="/share/:token" element={<SharedReport />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/generate" element={<Generate />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/reports/:reportId" element={<ReportDetail />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/settings" element={<Settings />} />

            <Route element={<AdminRoute />}>
              <Route path="/users" element={<Users />} />
              <Route path="/audit" element={<Audit />} />
            </Route>

            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
      </Routes>
    </>
  );
}
