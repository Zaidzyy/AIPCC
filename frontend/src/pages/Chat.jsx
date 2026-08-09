import {
  AlertTriangle,
  ArrowUp,
  Check,
  FileText,
  MessageSquare,
  Plus,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ChatWaveform } from "@/components/motion";
import {
  Badge,
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
  Textarea,
  Tooltip,
  useToast,
} from "@/components/ui";
import {
  useChat,
  useChats,
  useCreateChat,
  useDeleteChat,
  useDocuments,
  useSendMessage,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/apiClient";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

export function Chat() {
  const chats = useChats();
  const [selectedId, setSelectedId] = useState(null);
  const [composerOpen, setComposerOpen] = useState(false);

  // Derived, not synchronised through an effect: with nothing explicitly
  // chosen, land on the most recent conversation. Deleting one clears the
  // selection and this falls through to whatever is now newest.
  const activeId = selectedId ?? chats.data?.[0]?.chat_id ?? null;

  return (
    <div className="grid h-[calc(100dvh-9rem)] gap-6 lg:grid-cols-[16rem_1fr]">
      <ChatList
        query={chats}
        activeId={activeId}
        onSelect={setSelectedId}
        onNew={() => setComposerOpen(true)}
      />

      <div className="min-w-0">
        {activeId ? (
          <Conversation key={activeId} chatId={activeId} onDeleted={() => setSelectedId(null)} />
        ) : (
          <div className="flex h-full items-center justify-center rounded-lg border border-line bg-surface">
            <div className="text-center">
              <div className="mx-auto mb-2 w-64">
                <ChatWaveform />
              </div>
              <p className="font-mono text-sm font-medium text-ink">Talk to your data</p>
              <p className="mx-auto mt-1.5 max-w-xs text-sm text-ink-dim">
                Ask questions about an ingested log. Answers are grounded in the document you
                attach and cite the lines they came from.
              </p>
              <Button variant="primary" size="sm" className="mt-5" onClick={() => setComposerOpen(true)}>
                <Plus />
                New conversation
              </Button>
            </div>
          </div>
        )}
      </div>

      <NewChatDialog
        open={composerOpen}
        onOpenChange={setComposerOpen}
        onCreated={setSelectedId}
      />
    </div>
  );
}

function ChatList({ query, activeId, onSelect, onNew }) {
  return (
    <aside className="flex min-h-0 flex-col rounded-lg border border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
        <p className="eyebrow">Conversations</p>
        <Button variant="ghost" size="icon-sm" onClick={onNew} aria-label="New conversation">
          <Plus />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {query.isError ? (
          <ErrorState error={query.error} title="Could not load chats" onRetry={query.refetch} />
        ) : query.isPending ? (
          <div className="space-y-2 p-1">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
        ) : query.data.length === 0 ? (
          <p className="px-2 py-6 text-center text-[0.8125rem] text-ink-faint">
            No conversations yet.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {query.data.map((chat) => (
              <li key={chat.chat_id}>
                <button
                  type="button"
                  onClick={() => onSelect(chat.chat_id)}
                  className={cn(
                    "w-full rounded-md px-2.5 py-2 text-left transition-colors",
                    chat.chat_id === activeId
                      ? "bg-raised text-ink"
                      : "text-ink-dim hover:bg-raised/60 hover:text-ink",
                  )}
                >
                  <span className="block truncate text-[0.8125rem]">{chat.chat_name}</span>
                  <span className="mt-0.5 block text-xs text-ink-faint">
                    {formatRelative(chat.updated_at)}
                    {chat.attached_documents.length > 0 &&
                      ` · ${chat.attached_documents.length} doc${
                        chat.attached_documents.length === 1 ? "" : "s"
                      }`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function Conversation({ chatId, onDeleted }) {
  const query = useChat(chatId);
  const send = useSendMessage(chatId);
  const remove = useDeleteChat();
  const { toast } = useToast();

  const [draft, setDraft] = useState("");
  // Sources come back with the reply and are not persisted, so they are kept
  // for the current session only rather than faked on reload.
  const [sources, setSources] = useState({});
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [query.data?.messages?.length, send.isPending]);

  async function handleSend(event) {
    event?.preventDefault();
    const message = draft.trim();
    if (!message || send.isPending) return;

    setDraft("");
    try {
      const result = await send.mutateAsync(message);
      if (result.sources?.length) {
        setSources((current) => ({
          ...current,
          [result.assistant_message.message_id]: result.sources,
        }));
      }
    } catch (error) {
      toast({
        variant: "error",
        title: "No answer",
        description: errorMessage(error),
      });
    }
  }

  async function handleDelete() {
    try {
      await remove.mutateAsync(chatId);
      onDeleted();
    } catch (error) {
      toast({ variant: "error", title: "Delete failed", description: errorMessage(error) });
    }
  }

  if (query.isError) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-line bg-surface">
        <ErrorState error={query.error} title="Could not load this conversation" />
      </div>
    );
  }

  const chat = query.data;

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-line bg-surface">
      <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-sm font-medium text-ink">
            {query.isPending ? "…" : chat.chat_name}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {chat?.attached_documents?.length ? (
              chat.attached_documents.map((document) => (
                <Badge key={document.document_id} variant="outline">
                  {document.document_name}
                </Badge>
              ))
            ) : (
              <span className="text-xs text-ink-faint">
                No document attached — answers are not grounded in your logs.
              </span>
            )}
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={handleDelete}
          loading={remove.isPending}
          aria-label="Delete conversation"
        >
          <Trash2 />
        </Button>
      </header>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5">
        {query.isPending ? (
          <div className="space-y-4">
            <Skeleton className="h-12 w-2/3" />
            <Skeleton className="ml-auto h-16 w-3/4" />
          </div>
        ) : chat.messages.length === 0 ? (
          <EmptyState
            icon={MessageSquare}
            title="Ask the first question"
            description="Try: “What attacks are visible in this log, and which principal was involved?”"
          />
        ) : (
          chat.messages.map((message) => (
            <Message
              key={message.message_id}
              message={message}
              sources={sources[message.message_id]}
            />
          ))
        )}

        {send.isPending && (
          <div className="flex items-center gap-2.5" role="status">
            <span className="size-1.5 animate-pulse-dot rounded-full bg-ink-faint" />
            <span className="eyebrow">Retrieving and answering</span>
          </div>
        )}

        <div ref={endRef} />
      </div>

      <form onSubmit={handleSend} className="border-t border-line p-3">
        <div className="flex items-end gap-2">
          <Textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask about this log…"
            rows={1}
            className="min-h-9.5 max-h-40 py-2"
            aria-label="Message"
          />
          <Button
            type="submit"
            variant="primary"
            size="icon"
            disabled={!draft.trim() || send.isPending}
            aria-label="Send message"
          >
            <ArrowUp />
          </Button>
        </div>
        <p className="mt-1.5 px-1 text-xs text-ink-faint">
          Enter to send · Shift + Enter for a new line
        </p>
      </form>
    </div>
  );
}

function Message({ message, sources }) {
  const isUser = message.role === "human";
  const failed = message.status === "failed";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%]">
          <div className="rounded-lg rounded-br-sm border border-line-strong bg-raised px-3.5 py-2.5 text-sm leading-relaxed text-ink">
            {message.context}
          </div>
          {failed && (
            <p className="mt-1.5 flex items-center justify-end gap-1.5 text-xs text-critical">
              <AlertTriangle className="size-3" aria-hidden="true" />
              No answer was produced for this question.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[85%]">
      <p className="eyebrow mb-1.5">AIPCC</p>
      <div className="whitespace-pre-wrap text-sm leading-relaxed text-ink-dim">
        {message.context}
      </div>

      {sources?.length > 0 && (
        <details className="mt-3 rounded-md border border-line bg-void/50 px-3 py-2">
          <summary className="eyebrow cursor-pointer select-none">
            {sources.length} source{sources.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2.5 space-y-2.5">
            {sources.map((source, index) => (
              <li key={index}>
                <p className="ident text-xs text-ink">{source.document_name}</p>
                <p className="mt-0.5 line-clamp-3 font-mono text-xs leading-relaxed text-ink-faint">
                  {source.excerpt}
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function NewChatDialog({ open, onOpenChange, onCreated }) {
  const documents = useDocuments();
  const create = useCreateChat();
  const { toast } = useToast();

  const [name, setName] = useState("");
  const [selected, setSelected] = useState([]);

  function toggle(documentId) {
    setSelected((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId],
    );
  }

  async function handleCreate() {
    try {
      const chat = await create.mutateAsync({
        chatName: name.trim() || null,
        documentIds: selected,
      });
      onCreated(chat.chat_id);
      onOpenChange(false);
      setName("");
      setSelected([]);
    } catch (error) {
      toast({ variant: "error", title: "Could not start the chat", description: errorMessage(error) });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New conversation</DialogTitle>
          <DialogDescription>
            Attach the documents this conversation should be grounded in. Retrieval is scoped to
            them, so a chat with none attached cannot answer from your logs.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <p className="eyebrow">Name (optional)</p>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Named from your first question if left blank"
              maxLength={255}
            />
          </div>

          <div className="space-y-1.5">
            <p className="eyebrow">Documents</p>
            {documents.isPending ? (
              <Skeleton className="h-24 w-full" />
            ) : documents.data.length === 0 ? (
              <p className="text-sm text-ink-faint">
                Nothing ingested yet. Upload a log on the Generate page first.
              </p>
            ) : (
              <ul className="max-h-56 space-y-0.5 overflow-y-auto rounded-md border border-line p-1">
                {documents.data.map((document) => {
                  const active = selected.includes(document.document_id);
                  return (
                    <li key={document.document_id}>
                      <button
                        type="button"
                        onClick={() => toggle(document.document_id)}
                        aria-pressed={active}
                        className={cn(
                          "flex w-full items-center gap-2.5 rounded-sm px-2.5 py-2 text-left text-sm transition-colors",
                          active ? "bg-raised text-ink" : "text-ink-dim hover:bg-raised/60",
                        )}
                      >
                        <span
                          className={cn(
                            "flex size-4 shrink-0 items-center justify-center rounded-xs border",
                            active ? "border-ink bg-ink text-void" : "border-line-strong",
                          )}
                          aria-hidden="true"
                        >
                          {active && <Check className="size-3" strokeWidth={3} />}
                        </span>
                        <FileText className="size-3.5 shrink-0 text-ink-faint" aria-hidden="true" />
                        <span className="truncate">{document.document_name}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </DialogBody>

        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Tooltip content={selected.length === 0 ? "Answers will not be grounded in any log" : null}>
            <Button variant="primary" loading={create.isPending} onClick={handleCreate}>
              Start conversation
            </Button>
          </Tooltip>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
