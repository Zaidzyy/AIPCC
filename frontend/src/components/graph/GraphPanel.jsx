import { Network, TriangleAlert } from "lucide-react";
import { Suspense, lazy, useState } from "react";

import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  SeverityBadge,
  Skeleton,
  Tooltip,
} from "@/components/ui";
import { useReportGraph } from "@/hooks/queries";
import { SEVERITIES, severityToken } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The attack graph for one report.
 *
 * `GraphCanvas` is behind `React.lazy` for the same reason `ChartGrid` is: it
 * pulls in a physics engine, and a report page whose reader never opens the
 * graph should not download one. Nothing else may import `d3-force` directly,
 * or the chunk merges back into the entry bundle.
 */
const GraphCanvas = lazy(() =>
  import("./GraphCanvas").then((module) => ({ default: module.GraphCanvas })),
);

const TYPE_LABEL = {
  user: "User",
  host: "Host / address",
  process: "Process",
  file: "File",
  entity: "Unclassified",
};

export function GraphPanel({ reportId }) {
  const query = useReportGraph(reportId);
  const [selected, setSelected] = useState(null);

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Network className="size-4 text-ink-dim" aria-hidden="true" />
          Attack graph
        </CardTitle>
      </CardHeader>

      {query.isError ? (
        <ErrorState
          error={query.error}
          title="Could not build the graph"
          onRetry={query.refetch}
        />
      ) : query.isPending ? (
        <CardBody>
          <Skeleton className="h-[520px] w-full" />
        </CardBody>
      ) : query.data.nodes.length === 0 ? (
        // An empty canvas and a report with nothing to draw must not look the
        // same. This says which one it is, in the words the backend used.
        <EmptyState
          icon={Network}
          title="No entities to graph"
          description={query.data.empty_reason ?? "This report names no entities."}
        />
      ) : (
        <CardBody className="space-y-4">
          <Summary graph={query.data} />
          <div className="rounded-lg border border-line bg-void/40 p-2">
            <Suspense
              fallback={<div className="h-[520px] animate-pulse rounded-md bg-raised/40" />}
            >
              <GraphCanvas
                graph={query.data}
                selected={selected}
                onSelect={setSelected}
              />
            </Suspense>
          </div>
          <Legend />
          <NodeDetail
            node={query.data.nodes.find((node) => node.id === selected)}
            edges={query.data.edges}
            nodes={query.data.nodes}
          />
        </CardBody>
      )}
    </Card>
  );
}

function Summary({ graph }) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
      <p className="text-sm text-ink-dim">
        {graph.nodes.length} entities and {graph.edges.length} relationships, built from this
        report&rsquo;s own anomaly and timeline rows and the log lines its findings cite. No
        second extraction pass runs over the log.
      </p>
      {graph.truncated && (
        // A graph that quietly drops nodes to stay readable lies about the
        // report it claims to describe.
        <Badge className="border-medium/40 bg-medium/10 text-medium">
          <TriangleAlert className="size-3" aria-hidden="true" />
          Showing the {graph.nodes.length} highest-risk of {graph.total_nodes}
        </Badge>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-ink-faint">
      <span className="inline-flex items-center gap-2">
        <span className="inline-block h-px w-6 bg-line-strong" aria-hidden="true" />
        Observed interaction
      </span>
      <span className="inline-flex items-center gap-2">
        <span
          className="inline-block h-px w-6 border-t border-dashed border-line-strong"
          aria-hidden="true"
        />
        Cited in the same log lines
      </span>
      {SEVERITIES.slice()
        .reverse()
        .map((key) => {
          const token = severityToken(key);
          return (
            <span key={key} className="inline-flex items-center gap-1.5">
              <span className={cn("size-2 rounded-full", token.bg)} aria-hidden="true" />
              {token.label}
            </span>
          );
        })}
      <span className="inline-flex items-center gap-1.5">
        <span
          className="size-2 rounded-full border border-line-strong bg-raised"
          aria-hidden="true"
        />
        Unrated
      </span>
    </div>
  );
}

/**
 * What a node is, and the findings that gave it its colour.
 *
 * `basis` is shown on every finding rather than hidden, because "this finding
 * cites the same log lines" and "the model wrote this address into its
 * description" are different strengths of claim and an analyst deciding
 * whether to act on the graph needs to know which one they are looking at.
 */
function NodeDetail({ node, edges, nodes }) {
  if (!node) {
    return (
      <p className="text-sm text-ink-faint">
        Select a node to see the findings behind it.
      </p>
    );
  }

  const labels = Object.fromEntries(nodes.map((item) => [item.id, item.label]));
  const connections = edges.filter(
    (edge) => edge.source === node.id || edge.target === node.id,
  );

  return (
    <div className="rounded-lg border border-line bg-surface p-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-sm text-ink">{node.label}</span>
        <Badge>{TYPE_LABEL[node.type] ?? node.type}</Badge>
        {node.risk !== "unknown" && <SeverityBadge level={node.risk} />}
        <span className="text-xs text-ink-faint">
          {node.observations} observation{node.observations === 1 ? "" : "s"}
        </span>
      </div>

      {node.aliases.length > 0 && (
        <p className="mt-2 text-xs text-ink-faint">
          Also written as{" "}
          <span className="ident text-ink-dim">{node.aliases.join(", ")}</span> — merged
          because a single log row named both for the same principal.
        </p>
      )}

      {connections.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {connections.map((edge, index) => (
            <li
              key={index}
              className="rounded-sm border border-line px-2 py-1 font-mono text-[0.6875rem] text-ink-dim"
            >
              {edge.kind.replace(/_/g, " ")} ·{" "}
              {labels[edge.source === node.id ? edge.target : edge.source]}
              {edge.label ? ` · ${edge.label}` : ""}
            </li>
          ))}
        </ul>
      )}

      <p className="eyebrow mt-4 mb-2">Findings</p>
      <ul className="space-y-1.5">
        {node.findings.map((finding, index) => (
          <li
            key={index}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-void/40 px-3 py-2"
          >
            <span className="min-w-0">
              <span className="block truncate text-sm text-ink">
                {finding.title || "Untitled finding"}
              </span>
              <span className="block truncate text-xs text-ink-faint">
                {finding.section.replace(/_/g, " ")}
                {finding.detail ? ` · ${finding.detail}` : ""}
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              {finding.risk_level && <SeverityBadge level={finding.risk_level} />}
              <Tooltip content={BASIS[finding.basis] ?? finding.basis}>
                <span className="ident text-[0.625rem] text-ink-faint">{finding.basis}</span>
              </Tooltip>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const BASIS = {
  source: "This node was read out of this finding's own columns.",
  evidence: "This finding cites log lines that a finding naming this node also cites.",
  mention: "This node's name appears verbatim in this finding's text — a weaker link.",
};
