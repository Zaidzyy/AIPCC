import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { chatApi, documentsApi, reportsApi, usersApi } from "@/lib/api";

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
};

// --- Documents ------------------------------------------------------------

export function useDocuments() {
  return useQuery({ queryKey: keys.documents, queryFn: documentsApi.list });
}

export function useUploadDocument({ onProgress } = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file) => documentsApi.upload(file, onProgress),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.documents }),
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
    },
    // A failed generation still persists a report row with status "failed",
    // so the history list has changed either way.
    onError: () => queryClient.invalidateQueries({ queryKey: keys.reports }),
  });
}

export function useDeleteReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: reportsApi.remove,
    onSuccess: (_, reportId) => {
      queryClient.removeQueries({ queryKey: keys.report(reportId) });
      queryClient.invalidateQueries({ queryKey: keys.reports });
    },
  });
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
