import { Crosshair, Download, Loader2, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { MatrixGrid } from "@/components/attack/MatrixGrid";
import { TechniqueDialog } from "@/components/attack/TechniqueDialog";
import { PageHeader } from "@/components/common/PageHeader";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
  Tooltip,
  useToast,
} from "@/components/ui";
import { useAttackDetections, useAttackMatrix, useReports } from "@/hooks/queries";
import { attackApi } from "@/lib/api";
import { saveBlob } from "@/lib/download";

const ALL = "all";

/**
 * The MITRE ATT&CK matrix, populated from real reports.
 *
 * Everything on this page comes from two sources and they are kept visibly
 * apart: the grid is MITRE's published catalogue, vendored and pinned, and the
 * shading is this system's own output. The second is model-generated and is
 * therefore treated as a claim — which is what the "not on the matrix" panel
 * below the grid is for.
 */
export function AttackMatrix() {
  const [scope, setScope] = useState(ALL);
  const [dense, setDense] = useState("detected");
  const [selection, setSelection] = useState(null);

  const reportId = scope === ALL ? undefined : scope;
  const grid = useAttackMatrix();
  const found = useAttackDetections(reportId);
  const reports = useReports();

  return (
    <>
      <PageHeader
        eyebrow="Analysis"
        title="ATT&CK matrix"
        description={
          grid.data
            ? `MITRE ATT&CK Enterprise v${grid.data.attack_version} — ${grid.data.technique_count} techniques across ${grid.data.tactics.length} tactics. Shaded cells are techniques this system's reports named.`
            : "MITRE ATT&CK Enterprise, populated from generated reports."
        }
        actions={<ExportLayer reportId={reportId} disabled={!found.data} />}
      />

      <Card className="mb-6">
        <CardBody className="flex flex-wrap items-end gap-4">
          <div className="w-72 space-y-1.5">
            <p className="eyebrow">Scope</p>
            <Select value={scope} onValueChange={setScope}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All reports</SelectItem>
                {(reports.data ?? []).map((report) => (
                  <SelectItem key={report.report_id} value={report.report_id}>
                    {report.report_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <p className="eyebrow">Density</p>
            <Tabs value={dense} onValueChange={setDense}>
              <TabsList>
                <TabsTrigger value="detected">Detected only</TabsTrigger>
                <TabsTrigger value="full">Full matrix</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          {found.data && <Counts found={found.data} />}
        </CardBody>
      </Card>

      {grid.isError || found.isError ? (
        <Card>
          <ErrorState
            error={grid.error ?? found.error}
            title="Could not load the matrix"
            onRetry={() => {
              grid.refetch();
              found.refetch();
            }}
          />
        </Card>
      ) : grid.isPending || found.isPending ? (
        <Card>
          <CardBody className="space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-72 w-full" />
          </CardBody>
        </Card>
      ) : found.data.techniques_emitted === 0 ? (
        // "No report has named a technique" is not "the matrix failed to
        // load", and it is not a grid of empty cells either.
        <Card>
          <EmptyState
            icon={Crosshair}
            title="No techniques have been detected yet"
            description={
              found.data.reports_considered === 0
                ? "Generate a report first — the matrix is drawn from what reports find."
                : `${found.data.reports_considered} report(s) in scope, none of which identified an ATT&CK technique.`
            }
          />
        </Card>
      ) : (
        <>
          <Card className="mb-6">
            <CardBody>
              <MatrixGrid
                grid={grid.data}
                detections={found.data.detections}
                dense={dense === "detected"}
                onSelect={(technique, hit) => setSelection({ technique, hit })}
              />
            </CardBody>
          </Card>

          <Unplaced entries={found.data.unplaced} />
        </>
      )}

      <TechniqueDialog selection={selection} onClose={() => setSelection(null)} />
    </>
  );
}

function Counts({ found }) {
  const unverified = found.detections.filter((item) => !item.verified).length;
  const items = [
    { label: "Techniques", value: found.detections.length },
    { label: "Detections", value: found.techniques_emitted },
    { label: "Reports", value: found.reports_considered },
    { label: "Not on matrix", value: found.unplaced.length, warn: found.unplaced.length > 0 },
    { label: "Unverified", value: unverified, warn: unverified > 0 },
  ];

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
      {items.map(({ label, value, warn }) => (
        <div key={label}>
          <p className="eyebrow">{label}</p>
          <p
            className={`font-mono text-lg tabular-nums ${warn ? "text-medium" : "text-ink"}`}
          >
            {value}
          </p>
        </div>
      ))}
    </div>
  );
}

/**
 * Identifiers that could not be placed.
 *
 * These are the reason this page is not just a picture. A technique id that
 * does not exist has no cell — but dropping it would make the matrix look
 * cleaner than the output behind it, so it is reported here with the
 * validator's own sentence.
 */
function Unplaced({ entries }) {
  if (entries.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TriangleAlert className="size-4 text-medium" aria-hidden="true" />
          Reported, but not on the matrix
        </CardTitle>
      </CardHeader>
      <CardBody className="space-y-2">
        <p className="text-sm text-ink-dim">
          The model named these identifiers. They are checked against the vendored ATT&amp;CK
          catalogue and none of them can be drawn — so they are listed rather than shaded, and
          they are excluded from the Navigator layer.
        </p>
        <ul className="space-y-1.5">
          {entries.map((entry) => (
            <li
              key={`${entry.value}-${entry.reason}`}
              className="flex flex-wrap items-baseline justify-between gap-2 rounded-md border border-medium/25 bg-medium/5 px-3 py-2"
            >
              <span className="font-mono text-sm text-medium">{entry.value}</span>
              <span className="min-w-0 flex-1 text-xs text-ink-dim">{entry.detail}</span>
              <span className="font-mono text-xs text-ink-faint tabular-nums">
                ×{entry.count}
              </span>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

function ExportLayer({ reportId, disabled }) {
  const { toast } = useToast();
  const [pending, setPending] = useState(false);

  async function download() {
    setPending(true);
    try {
      const { blob, filename } = await attackApi.navigatorLayer(reportId);
      saveBlob(blob, filename);
      toast({ variant: "success", title: `Exported ${filename}` });
    } catch {
      // Same reasoning as the report export: the endpoint answers with a blob,
      // so an error arrives as JSON inside a Blob that cannot be read back.
      toast({
        variant: "error",
        title: "Export failed",
        description: "The layer could not be built.",
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <Tooltip content="A layer file for MITRE's own ATT&CK Navigator (layer format 4.5)">
      <Button variant="ghost" size="sm" onClick={download} disabled={disabled || pending}>
        {pending ? <Loader2 className="animate-spin" /> : <Download />}
        Navigator layer
      </Button>
    </Tooltip>
  );
}
