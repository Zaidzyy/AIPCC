import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
} from "d3-force";
import { useMemo } from "react";

import { severityToken } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A force-directed layout, drawn as plain SVG.
 *
 * **Library choice.** `d3-force` and nothing else. It is only the simulation —
 * positions in, positions out, no renderer, no canvas, no opinions about
 * styling — and the whole lazy chunk, this component included, measures
 * 17.5 kB raw / 6.9 kB gzipped in the production build. The alternatives were rejected on cost
 * and on fit. `react-force-graph` pulls in three.js; `cytoscape` and
 * `vis-network` are 300–400 kB and each arrive with a complete visual language
 * this app would then have to override. Rendering the nodes ourselves as SVG
 * keeps the design system intact — this is the same choice `components/ui/`
 * makes about Radix: take the behaviour that is hard, write the appearance.
 *
 * The whole module sits behind a `React.lazy` boundary in `GraphPanel`, for
 * the reason Recharts does: a report page that never opens the graph should
 * not download a physics engine.
 *
 * **Legibility over completeness.** The simulation runs to a fixed tick count
 * and stops rather than animating forever — a graph that never settles cannot
 * be read, and a permanently running requestAnimationFrame loop on a page an
 * analyst leaves open is a laptop fan. Labels are drawn for every node,
 * because an unlabelled circle is a decoration.
 */

const WIDTH = 900;
const HEIGHT = 520;
// Enough for the layout to settle at this size; measured, not guessed — below
// about 200 the clusters are still visibly drifting apart.
const TICKS = 300;

const TYPE_GLYPH = {
  user: "◍",
  host: "▣",
  process: "▶",
  file: "▤",
  entity: "◇",
};

const RADIUS = { user: 13, host: 12, process: 11, file: 11, entity: 10 };

export function GraphCanvas({ graph, selected, onSelect }) {
  // Laid out in a memo rather than an effect, because the simulation is
  // synchronous: `tick(n)` runs to completion and returns positions. Wrapping
  // that in an effect + setState would render once with nothing, once with the
  // layout, and give React a reason to warn about both.
  const layout = useMemo(() => {
    // The simulation mutates the objects it is given, so it gets copies — d3
    // would otherwise write x/y onto the query cache's data.
    const nodes = graph.nodes.map((node) => ({ ...node }));
    const links = graph.edges.map((edge) => ({ ...edge }));

    forceSimulation(nodes)
      .force(
        "link",
        forceLink(links)
          .id((node) => node.id)
          // Co-occurrence is a weaker claim than an observed connection, so it
          // pulls less hard: the strong relationships shape the picture.
          .distance((link) => (link.kind === "co_occurs" ? 130 : 90))
          .strength((link) => (link.kind === "co_occurs" ? 0.25 : 0.8)),
      )
      .force("charge", forceManyBody().strength(-320))
      .force("center", forceCenter(WIDTH / 2, HEIGHT / 2))
      // Isolated nodes have no link pulling them anywhere, so without these two
      // they drift off the canvas and the graph appears to have lost them.
      .force("x", forceX(WIDTH / 2).strength(0.06))
      .force("y", forceY(HEIGHT / 2).strength(0.09))
      .force("collide", forceCollide((node) => (RADIUS[node.type] ?? 10) + 26))
      .stop()
      // A fixed tick count, then stop. A graph that never settles cannot be
      // read, and a permanent animation frame on a page an analyst leaves open
      // is a laptop fan.
      .tick(TICKS);

    return { nodes, links };
  }, [graph]);

  const neighbours = new Set(
    selected
      ? layout.links
          .filter((link) => id(link.source) === selected || id(link.target) === selected)
          .flatMap((link) => [id(link.source), id(link.target)])
      : [],
  );

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full touch-none select-none"
      role="img"
      aria-label={`Attack graph: ${layout.nodes.length} entities, ${layout.links.length} relationships`}
    >
      <g>
        {layout.links.map((link, index) => {
          const dim = selected && !(neighbours.has(id(link.source)) && neighbours.has(id(link.target)));
          const token = severityToken(link.risk);
          return (
            <g key={index} opacity={dim ? 0.12 : 1}>
              <line
                x1={link.source.x}
                y1={link.source.y}
                x2={link.target.x}
                y2={link.target.y}
                stroke="currentColor"
                className={link.risk === "unknown" ? "text-line-strong" : token.text}
                strokeWidth={Math.min(1 + link.weight * 0.6, 4)}
                strokeDasharray={link.kind === "co_occurs" ? "3 4" : undefined}
                strokeOpacity={link.kind === "co_occurs" ? 0.5 : 0.85}
              />
              {link.label && (
                <text
                  x={(link.source.x + link.target.x) / 2}
                  y={(link.source.y + link.target.y) / 2 - 4}
                  textAnchor="middle"
                  className="fill-ink-faint font-mono text-[8px]"
                >
                  {link.label}
                </text>
              )}
            </g>
          );
        })}
      </g>

      <g>
        {layout.nodes.map((node) => {
          const token = severityToken(node.risk);
          const active = selected === node.id;
          const dim = selected && !active && !neighbours.has(node.id);
          const radius = RADIUS[node.type] ?? 10;

          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              opacity={dim ? 0.2 : 1}
              className="cursor-pointer"
              onClick={() => onSelect(active ? null : node.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(active ? null : node.id);
                }
              }}
            >
              <circle
                r={radius}
                // `fill="currentColor"` plus the severity's *text* class, not
                // its `bg` class. Tailwind's `bg-*` sets `background-color`,
                // which an SVG shape ignores entirely — so every rated node
                // rendered as an invisible transparent disc, which looked
                // exactly like a node the layout had lost. Found by looking at
                // it, not by reading it.
                fill="currentColor"
                className={cn(
                  node.risk === "unknown" ? "text-raised" : token.text,
                  node.risk === "unknown" ? "stroke-line-strong" : "stroke-void",
                )}
                strokeWidth={active ? 3 : 1.5}
                fillOpacity={node.risk === "unknown" ? 1 : 0.92}
              />
              {active && (
                <circle
                  r={radius + 5}
                  className="fill-none stroke-ink"
                  strokeWidth={1.5}
                  strokeDasharray="2 3"
                />
              )}
              <text
                textAnchor="middle"
                dy={4}
                className={cn(
                  "pointer-events-none font-mono text-[10px]",
                  node.risk === "unknown" ? "fill-ink-dim" : "fill-void",
                )}
              >
                {TYPE_GLYPH[node.type] ?? TYPE_GLYPH.entity}
              </text>
              <text
                textAnchor="middle"
                dy={radius + 12}
                className="pointer-events-none fill-ink font-mono text-[9px]"
              >
                {truncate(node.label)}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

const id = (endpoint) => (typeof endpoint === "object" ? endpoint.id : endpoint);

function truncate(label, limit = 22) {
  return label.length > limit ? `${label.slice(0, limit - 1)}…` : label;
}
