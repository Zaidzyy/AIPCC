import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  alertsApi,
  chatApi,
  dashboardApi,
  documentsApi,
  reportsApi,
  sharesApi,
  usersApi,
} from "@/lib/api";

/**
 * Every server interaction in the app.
 *
 * Query keys are centralised so an invalidation cannot miss a cache entry
 * because a page spelled its key differently — no component builds its own.
 */
export const keys = {
  documents: ["documents"],
  document: (id) => ["documents", id],
  reports: ["reports"],
  report: (id) => ["reports", id],
  users: ["users"],
  chats: ["chats"],
  chat: (id) => ["chats", id],
  // The window is part of the key: /dashboard/reports-over-time?days=7 and
  // ?days=90 are different responses and must not share a cache entry.
  dashboard: ["dashboard"],
  dashboardSummary: ["dashboard", "summary"],
  dashboardReports: (days) => ["dashboard", "reports-over-time", days],
  dashboardSeverity: ["dashboard", "severity"],
  dashboardAttacks: (limit) => ["dashboard", "top-attack-types", limit],
  dashboardAnomalies: (days) => ["dashboard", "anomalies-over-time", days],
  alerts: ["alerts"],
  alertList: (status) => ["alerts", status ?? "all"],
  shares: (reportId) => ["reports", reportId, "shares"],
  // The public read is keyed on the token and lives outside every other key
  // space: nothing an authenticated page invalidates should touch it.
  sharedReport: (token) => ["share", token],
};

// --- Alerts ---------------------------------------------------------------

export function useAlerts(status) {
  return useQuery({
    queryKey: keys.alertList(status),
    queryFn: () => alertsApi.list(status),
  });
}

function useAlertMutation(mutationFn) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.alerts });
      // The KPI row counts open alerts, so resolving one changes the dashboard.
      queryClient.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
}

export function useSetAlertStatus() {
  return useAlertMutation(({ alertId, status }) => alertsApi.setStatus(alertId, status));
}

export function useDeleteAlert() {
  return useAlertMutation(alertsApi.remove);
}

// --- Dashboard ------------------------------------------------------------

export function useDashboardSummary() {
  return useQuery({ queryKey: keys.dashboardSummary, queryFn: dashboardApi.summary });
}

export function useReportsOverTime(days) {
  return useQuery({
    queryKey: keys.dashboardReports(days),
    queryFn: () => dashboardApi.reportsOverTime(days),
  });
}

export function useSeverityBreakdown() {
  return useQuery({ queryKey: keys.dashboardSeverity, queryFn: dashboardApi.severity });
}

export function useTopAttackTypes(limit = 8) {
  return useQuery({
    queryKey: keys.dashboardAttacks(limit),
    queryFn: () => dashboardApi.topAttackTypes(limit),
  });
}

export function useAnomaliesOverTime(days) {
  return useQuery({
    queryKey: keys.dashboardAnomalies(days),
    queryFn: () => dashboardApi.anomaliesOverTime(days),
  });
}

// --- Documents ------------------------------------------------------------

export function useDocuments() {
  return useQuery({ queryKey: keys.documents, queryFn: documentsApi.list });
}

export function useUploadDocument({ onProgress } = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file) => documentsApi.upload(file, onProgress),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.documents });
      queryClient.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
}

// --- Reports --------------------------------------------------------------

export function useReports() {
  return useQuery({ queryKey: keys.reports, queryFn: reportsApi.list });
}

export function useReport(reportId) {
  return useQuery({
    queryKey: keys.report(reportId),
    queryFn: () => reportsApi.get(reportId),
    enabled: Boolean(reportId),
  });
}

export function useGenerateReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: reportsApi.generate,
    onSuccess: (report) => {
      queryClient.setQueryData(keys.report(report.report_id), report);
      queryClient.invalidateQueries({ queryKey: keys.reports });
      // Every aggregate on the dashboard is now one report out of date.
      queryClient.invalidateQueries({ queryKey: keys.dashboard });
    },
    // A failed generation still persists a report row with status "failed",
    // so the history list and the aggregates have changed either way.
    onError: () => {
      queryClient.invalidateQueries({ queryKey: keys.reports });
      queryClient.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
}

export function useDeleteReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: reportsApi.remove,
    onSuccess: (_, reportId) => {
      queryClient.removeQueries({ queryKey: keys.report(reportId) });
      queryClient.invalidateQueries({ queryKey: keys.reports });
      queryClient.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
}

export function useSetClassification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ reportId, classification }) =>
      reportsApi.setClassification(reportId, classification),
    onSuccess: (summary) => {
      queryClient.invalidateQueries({ queryKey: keys.report(summary.report_id) });
      queryClient.invalidateQueries({ queryKey: keys.reports });
      // Raising a report to Confidential stops its links resolving, so what the
      // share list says about them is now out of date.
      queryClient.invalidateQueries({ queryKey: keys.shares(summary.report_id) });
    },
  });
}

/**
 * Export is a mutation, not a query: it produces a file the user takes away,
 * it has no cached representation, and firing it twice must download twice.
 */
export function useExportReport() {
  return useMutation({ mutationFn: reportsApi.exportReport });
}

// --- Sharing --------------------------------------------------------------

export function useReportShares(reportId, { enabled = true } = {}) {
  return useQuery({
    queryKey: keys.shares(reportId),
    queryFn: () => sharesApi.list(reportId),
    enabled: Boolean(reportId) && enabled,
  });
}

export function useCreateShare(reportId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) => sharesApi.create({ reportId, ...input }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.shares(reportId) }),
  });
}

export function useRevokeShare(reportId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: sharesApi.revoke,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.shares(reportId) }),
  });
}

export function useSharedReport(token) {
  return useQuery({
    queryKey: keys.sharedReport(token),
    queryFn: () => sharesApi.getShared(token),
    enabled: Boolean(token),
    // A link that is revoked, expired or reclassified stays that way. Retrying
    // a 403/404/410 only delays telling the recipient what happened.
    retry: false,
  });
}

export function useExportSharedReport() {
  return useMutation({ mutationFn: sharesApi.exportShared });
}

// --- Users (admin) --------------------------------------------------------

export function useUsers({ enabled = true } = {}) {
  return useQuery({ queryKey: keys.users, queryFn: usersApi.list, enabled });
}

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: usersApi.create,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.users }),
  });
}

export function useSetUserRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }) => usersApi.setRole(userId, role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.users }),
  });
}

export function useSetUserStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, status }) => usersApi.setStatus(userId, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.users }),
  });
}

export function useDeleteUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: usersApi.remove,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.users }),
  });
}

// --- Chat -----------------------------------------------------------------

export function useChats() {
  return useQuery({ queryKey: keys.chats, queryFn: chatApi.list });
}

export function useChat(chatId) {
  return useQuery({
    queryKey: keys.chat(chatId),
    queryFn: () => chatApi.get(chatId),
    enabled: Boolean(chatId),
  });
}

export function useCreateChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: chatApi.create,
    onSuccess: (chat) => {
      queryClient.setQueryData(keys.chat(chat.chat_id), chat);
      queryClient.invalidateQueries({ queryKey: keys.chats });
    },
  });
}

export function useSendMessage(chatId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (message) => chatApi.sendMessage(chatId, message),
    onSuccess: ({ user_message, assistant_message }) => {
      // Append both sides rather than refetching: the transcript is the one
      // place in the app where a spinner replacing the conversation would be
      // actively disorienting.
      queryClient.setQueryData(keys.chat(chatId), (previous) =>
        previous
          ? {
              ...previous,
              messages: [...previous.messages, user_message, assistant_message],
            }
          : previous,
      );
      queryClient.invalidateQueries({ queryKey: keys.chats });
    },
    // The question was persisted even though the answer failed, so the
    // transcript on the server no longer matches what is cached here.
    onError: () => queryClient.invalidateQueries({ queryKey: keys.chat(chatId) }),
  });
}

export function useDeleteChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: chatApi.remove,
    onSuccess: (_, chatId) => {
      queryClient.removeQueries({ queryKey: keys.chat(chatId) });
      queryClient.invalidateQueries({ queryKey: keys.chats });
    },
  });
}
