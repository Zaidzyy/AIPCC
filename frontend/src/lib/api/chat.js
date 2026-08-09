import { apiClient } from "@/lib/apiClient";

export async function list() {
  const { data } = await apiClient.get("/chats");
  return data;
}

export async function get(chatId) {
  const { data } = await apiClient.get(`/chats/${chatId}`);
  return data;
}

/** `documentIds` grounds the conversation. A chat with none retrieves nothing. */
export async function create({ chatName, documentIds = [] } = {}) {
  const { data } = await apiClient.post("/chats", {
    chat_name: chatName ?? null,
    document_ids: documentIds,
  });
  return data;
}

export async function sendMessage(chatId, message) {
  const { data } = await apiClient.post(`/chats/${chatId}/messages`, { message });
  return data;
}

export async function remove(chatId) {
  await apiClient.delete(`/chats/${chatId}`);
}
