import { FileText, Search, Sparkles, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/common/PageHeader";
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  IntegrityBadge,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SkeletonRows,
  StatusBadge,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Tooltip,
  useToast,
} from "@/components/ui";
import { useDeleteReport, useReports } from "@/hooks/queries";
import { errorMessage } from "@/lib/apiClient";
import { formatDateTime, formatRelative, shortId } from "@/lib/format";

const STATUSES = ["all", "complete", "partial", "failed"];

export function Reports() {
  const query = useReports();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [pendingDelete, setPendingDelete] = useState(null);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (query.data ?? []).filter((report) => {
      if (status !== "all" && report.status !== status) return false;
      if (!term) return true;
      return (
        report.report_name.toLowerCase().includes(term) ||
        report.report_id.toLowerCase().startsWith(term)
      );
    });
  }, [query.data, search, status]);

  return (
    <>
      <PageHeader
        eyebrow="Analysis"
        title="Reports"
        description="Every report generated from your ingested logs."
        actions={
          <Button variant="primary" asChild>
            <Link to="/generate">
              <Sparkles />
              Generate report
            </Link>
          </Button>
        }
      />

      {query.data?.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="relative min-w-56 flex-1">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-ink-faint"
              aria-hidden="true"
            />
            <Input
              className="pl-8.5"
              placeholder="Filter by name or id"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              aria-label="Filter reports"
            />
          </div>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUSES.map((value) => (
                <SelectItem key={value} value={value}>
                  {value === "all" ? "All statuses" : value[0].toUpperCase() + value.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      <Card className="overflow-hidden">
        {query.isError ? (
          <ErrorState error={query.error} title="Could not load reports" onRetry={query.refetch} />
        ) : query.isPending ? (
          <SkeletonRows rows={6} columns={4} />
        ) : query.data.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No reports yet"
            description="Upload a security log and generate your first report."
            action={
              <Button variant="primary" size="sm" asChild>
                <Link to="/generate">Generate a report</Link>
              </Button>
            }
          />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={Search}
            title="No matches"
            description="No report matches the current filter."
            action={
              <Button
                size="sm"
                onClick={() => {
                  setSearch("");
                  setStatus("all");
                }}
              >
                Clear filters
              </Button>
            }
          />
        ) : (
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>Report</TH>
                <TH>Status</TH>
                <TH className="hidden lg:table-cell">Integrity</TH>
                <TH className="hidden md:table-cell">Classification</TH>
                <TH className="hidden sm:table-cell">Generated</TH>
                <TH className="w-12 text-right">
                  <span className="sr-only">Actions</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {visible.map((report) => (
                <TR key={report.report_id}>
                  <TD className="align-middle">
                    <Link
                      to={`/reports/${report.report_id}`}
                      className="block font-medium text-ink hover:underline"
                    >
                      {report.report_name}
                    </Link>
                    <Tooltip content={report.report_id}>
                      <span className="ident text-xs text-ink-faint">
                        {shortId(report.report_id)}
                      </span>
                    </Tooltip>
                  </TD>
                  <TD className="align-middle">
                    <StatusBadge status={report.status} />
                  </TD>
                  <TD className="hidden align-middle lg:table-cell">
                    <IntegrityBadge state={report.integrity_state} />
                  </TD>
                  <TD className="hidden align-middle md:table-cell">
                    <Badge variant="outline">{report.classification}</Badge>
                  </TD>
                  <TD className="hidden align-middle sm:table-cell">
                    <Tooltip content={formatDateTime(report.generated_at)}>
                      <span className="text-[0.8125rem]">
                        {formatRelative(report.generated_at)}
                      </span>
                    </Tooltip>
                  </TD>
                  <TD className="align-middle text-right">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Delete ${report.report_name}`}
                      onClick={() => setPendingDelete(report)}
                    >
                      <Trash2 />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <DeleteReportDialog report={pendingDelete} onClose={() => setPendingDelete(null)} />
    </>
  );
}

function DeleteReportDialog({ report, onClose }) {
  const remove = useDeleteReport();
  const { toast } = useToast();

  async function confirm() {
    try {
      await remove.mutateAsync(report.report_id);
      toast({ variant: "success", title: "Report deleted" });
      onClose();
    } catch (error) {
      toast({ variant: "error", title: "Delete failed", description: errorMessage(error) });
    }
  }

  return (
    <Dialog open={Boolean(report)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete this report?</DialogTitle>
          <DialogDescription>
            {report?.report_name} and all of its findings are removed permanently. The source
            document stays ingested.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="hidden" />
        <DialogFooter>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={remove.isPending} onClick={confirm}>
            Delete report
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
