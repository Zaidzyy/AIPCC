import { AlertTriangle, Check, Copy, Link2, Loader2, Trash2 } from "lucide-react";
import { useState } from "react";

import { ClassificationIcon } from "@/components/report/ClassificationSelect";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Field,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Separator,
  Textarea,
  useToast,
} from "@/components/ui";
import { useCreateShare, useReportShares, useRevokeShare } from "@/hooks/queries";
import { errorMessage } from "@/lib/apiClient";
import { classificationToken, formatDateTime, formatRelative } from "@/lib/format";

const WINDOWS = [
  { value: "24", label: "24 hours" },
  { value: "168", label: "7 days" },
  { value: "720", label: "30 days" },
  { value: "never", label: "Does not expire" },
];

// The server requires 10 characters. Stated here so the field can say so before
// the request rather than after it.
const MIN_JUSTIFICATION = 10;

export function ShareDialog({ report }) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm">
          <Link2 />
          Share
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Share this report</DialogTitle>
          <DialogDescription>
            A link grants read-only access to this one report. It carries no account, and
            nobody who opens it can reach anything else.
          </DialogDescription>
        </DialogHeader>
        {/* Mounted only while open, so the share list is fetched when somebody
            asks for it rather than on every Report Detail render. */}
        {open && <ShareBody report={report} />}
      </DialogContent>
    </Dialog>
  );
}

function ShareBody({ report }) {
  const { toast } = useToast();
  const shares = useReportShares(report.report_id);
  const create = useCreateShare(report.report_id);

  const [window, setWindow] = useState("168");
  const [label, setLabel] = useState("");
  const [justification, setJustification] = useState("");
  const [minted, setMinted] = useState(null);

  const classification = classificationToken(report.classification);
  const needsOverride = !classification.shareable;
  const justificationTooShort =
    needsOverride && justification.trim().length < MIN_JUSTIFICATION;

  async function handleCreate(event) {
    event.preventDefault();
    try {
      const share = await create.mutateAsync({
        expiresInHours: window === "never" ? null : Number(window),
        label,
        justification: needsOverride ? justification.trim() : null,
      });
      setMinted(share);
      setLabel("");
      setJustification("");
    } catch (error) {
      toast({ variant: "error", title: "Could not create link", description: errorMessage(error) });
    }
  }

  return (
    <DialogBody className="space-y-5">
      <div className="flex items-start gap-2.5 rounded-md border border-line bg-raised px-3.5 py-2.5">
        <ClassificationIcon level={report.classification} className="mt-0.5 size-3.5 shrink-0 text-ink-faint" />
        <p className="text-[0.8125rem] leading-snug text-ink-dim">
          <span className="text-ink">{classification.label}</span> — {classification.description}
        </p>
      </div>

      {minted ? (
        <MintedLink share={minted} onDone={() => setMinted(null)} />
      ) : (
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <p className="eyebrow">Expires</p>
              <Select value={window} onValueChange={setWindow}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WINDOWS.map(({ value, label: text }) => (
                    <SelectItem key={value} value={value}>
                      {text}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Field label="Label" hint="Who this link is for. Only you see it.">
              {(props) => (
                <Input
                  {...props}
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="External counsel"
                  maxLength={120}
                />
              )}
            </Field>
          </div>

          {needsOverride && (
            <div className="rounded-md border border-medium/30 bg-medium/8 p-3.5">
              <div className="flex items-start gap-2.5">
                <AlertTriangle
                  className="mt-0.5 size-4 shrink-0 text-medium"
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1 space-y-2.5">
                  <p className="text-[0.8125rem] leading-snug text-ink-dim">
                    Sharing a Confidential report is an override. Your reason is stored against
                    the link and raises a security alert.
                  </p>
                  <Field
                    label="Justification"
                    required
                    hint={`At least ${MIN_JUSTIFICATION} characters.`}
                  >
                    {(props) => (
                      <Textarea
                        {...props}
                        value={justification}
                        onChange={(event) => setJustification(event.target.value)}
                        placeholder="Requested by the incident commander for the 09:00 bridge."
                        maxLength={500}
                        className="min-h-16"
                      />
                    )}
                  </Field>
                </div>
              </div>
            </div>
          )}

          <Button
            type="submit"
            variant="primary"
            loading={create.isPending}
            disabled={justificationTooShort}
          >
            <Link2 />
            Create link
          </Button>
        </form>
      )}

      <Separator />
      <ExistingLinks reportId={report.report_id} query={shares} />
    </DialogBody>
  );
}

/**
 * The token exists exactly once, in the create response. There is no endpoint
 * that can show it again — only its SHA-256 is stored — so this panel has to
 * be unmistakable about that rather than looking like a row in a list.
 */
function MintedLink({ share, onDone }) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(share.url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast({
        variant: "error",
        title: "Could not copy",
        description: "Select the link and copy it manually.",
      });
    }
  }

  return (
    <div className="rounded-md border border-ok/35 bg-ok/8 p-3.5">
      <p className="font-mono text-[0.8125rem] font-medium text-ok">Link created</p>
      <p className="mt-1 text-[0.8125rem] text-ink-dim">
        Copy it now. It is stored hashed, so it cannot be shown again — but it can be revoked.
      </p>
      <div className="mt-3 flex gap-2">
        <Input readOnly value={share.url} onFocus={(event) => event.target.select()} />
        <Button variant="secondary" onClick={copy}>
          {copied ? <Check /> : <Copy />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <Button variant="ghost" size="sm" className="mt-2 -ml-3" onClick={onDone}>
        Create another
      </Button>
    </div>
  );
}

function ExistingLinks({ reportId, query }) {
  const { toast } = useToast();
  const revoke = useRevokeShare(reportId);
  const [revoking, setRevoking] = useState(null);

  async function handleRevoke(shareId) {
    setRevoking(shareId);
    try {
      await revoke.mutateAsync(shareId);
      toast({ variant: "success", title: "Link revoked" });
    } catch (error) {
      toast({ variant: "error", title: "Could not revoke", description: errorMessage(error) });
    } finally {
      setRevoking(null);
    }
  }

  if (query.isPending) {
    return <p className="text-[0.8125rem] text-ink-faint">Loading links…</p>;
  }
  if (query.isError) {
    return (
      <p className="text-[0.8125rem] text-critical">
        Could not load existing links — {errorMessage(query.error)}
      </p>
    );
  }
  if (!query.data.length) {
    return (
      <p className="text-[0.8125rem] text-ink-faint">
        No links have been created for this report.
      </p>
    );
  }

  return (
    <div className="space-y-1">
      <p className="eyebrow">Existing links</p>
      <ul className="divide-y divide-line/70">
        {query.data.map((share) => (
          <li key={share.share_id} className="flex items-start justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <p className="text-[0.8125rem] text-ink">
                {share.label || "Untitled link"}
                {share.override_justification && (
                  <span className="ml-2 text-xs text-medium">override</span>
                )}
              </p>
              <p className="mt-0.5 text-xs text-ink-faint">
                <ShareState share={share} />
                <span className="mx-1.5">·</span>
                {share.view_count} view{share.view_count === 1 ? "" : "s"}
                {share.last_viewed_at && <> · last {formatRelative(share.last_viewed_at)}</>}
              </p>
            </div>
            {share.revoked ? (
              <span className="shrink-0 text-xs text-ink-faint">Revoked</span>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleRevoke(share.share_id)}
                disabled={revoking === share.share_id}
              >
                {revoking === share.share_id ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Trash2 />
                )}
                Revoke
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * `active` is computed by the server against its own clock. Recomputing it here
 * from `expires_at` would make the dialog and the link itself disagree for
 * anyone whose machine clock is off.
 */
function ShareState({ share }) {
  if (share.revoked) return <>Revoked {formatRelative(share.revoked_at)}</>;
  if (!share.active) return <>Expired {formatRelative(share.expires_at)}</>;
  if (!share.expires_at) return <>Does not expire</>;
  return <>Expires {formatDateTime(share.expires_at)}</>;
}
