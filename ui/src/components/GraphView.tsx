// The authority graph, drawn with Cytoscape, with a table alternative that lists the same
// nodes and edges (for keyboard and screen-reader users, and when drawing is unavailable).

import cytoscape, { type Core, type StylesheetJson } from "cytoscape";
import { Maximize2, Network, Table2, ZoomIn, ZoomOut } from "../icons";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { useThemeVersion } from "../theme";
import type { GraphElement } from "../types";
import { Card, Tip } from "./ui";

const SHAPES: Record<string, string> = {
  Principal: "ellipse",
  Utterance: "round-rectangle",
  Summary: "round-rectangle",
  Instruction: "hexagon",
  Scope: "tag",
  Agent: "diamond",
  Action: "rectangle",
  Decision: "star",
  Approval: "round-triangle",
};

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function stylesheet(): StylesheetJson {
  const text = cssVar("--text", "#1b1f24");
  const muted = cssVar("--muted", "#5b6470");
  const allow = cssVar("--allow", "#1a7f37");
  const confirm = cssVar("--confirm", "#9a6700");
  const deny = cssVar("--deny", "#cf222e");
  const quarantine = cssVar("--quarantine", "#8250df");
  const accent = cssVar("--accent", "#0969da");
  return [
    {
      selector: "node",
      style: {
        label: "data(caption)",
        "font-size": 9,
        "font-family": "Inter Variable, system-ui, sans-serif",
        color: text,
        "text-background-color": cssVar("--surface", "#ffffff"),
        "text-background-opacity": 0.85,
        "text-background-padding": "2px",
        "text-background-shape": "roundrectangle",
        "text-wrap": "ellipsis",
        "text-max-width": "120px",
        "text-valign": "bottom",
        "text-margin-y": 4,
        "background-color": cssVar("--node", "#d0d7de"),
        "border-width": 1,
        "border-color": muted,
        width: 24,
        height: 24,
        "transition-property": "width, height, border-width, background-color",
        "transition-duration": 0.2,
      },
    },
    ...Object.entries(SHAPES).map(([label, shape]) => ({
      selector: `node[label = "${label}"]`,
      style: { shape: shape as cytoscape.Css.NodeShape },
    })),
    { selector: "node.principal", style: { "background-color": accent } },
    { selector: "node.agent", style: { "background-color": cssVar("--agent", "#57606a") } },
    { selector: "node.untrusted", style: { "border-style": "dashed", opacity: 0.6 } },
    { selector: "node.mixed", style: { "border-style": "dotted" } },
    { selector: "node.allow", style: { "background-color": allow } },
    { selector: "node.confirm", style: { "background-color": confirm } },
    { selector: "node.deny", style: { "background-color": deny } },
    { selector: "node.quarantined", style: { "background-color": quarantine } },
    { selector: "node.revoked", style: { "border-color": deny, "border-width": 2 } },
    {
      selector: "edge",
      style: {
        width: 1,
        "line-color": muted,
        "target-arrow-color": muted,
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "arrow-scale": 0.7,
        opacity: 0.75,
        label: "data(label)",
        "font-size": 6,
        color: muted,
        "text-rotation": "autorotate",
      },
    },
    { selector: "edge.untrusted", style: { "line-style": "dashed" } },
    { selector: "edge.revoked", style: { "line-style": "dashed", "line-color": deny } },
    {
      selector: ".highlight",
      style: {
        "border-width": 3,
        "border-color": accent,
        "line-color": accent,
        "target-arrow-color": accent,
        width: 3,
        "z-index": 10,
      },
    },
    { selector: "node.highlight", style: { width: 32, height: 32 } },
    { selector: "edge.highlight", style: { opacity: 1 } },
    // The explorer: a traced lineage stands out and everything else steps back.
    { selector: ".faded", style: { opacity: 0.12, "text-opacity": 0 } },
    { selector: ".hidden", style: { display: "none" } },
    {
      selector: ".traced",
      style: {
        "border-width": 2,
        "border-color": accent,
        "line-color": accent,
        "target-arrow-color": accent,
        opacity: 1,
      },
    },
    {
      selector: "node.focus",
      style: {
        "border-width": 4,
        "border-color": accent,
        width: 36,
        height: 36,
        "underlay-color": accent,
        "underlay-opacity": 0.18,
        "underlay-padding": 8,
        "underlay-shape": "ellipse",
        "z-index": 20,
      },
    },
    { selector: "node:active, node:selected", style: { "overlay-opacity": 0.08 } },
  ];
}

export interface GraphViewProps {
  elements: GraphElement[];
  /** Extra ids to highlight, on top of what the server marked. */
  highlight?: Iterable<string>;
  truncated?: boolean;
  onSelect?: (element: GraphElement) => void;
  height?: number;
  /** The explorer's state: the lineage traced (everything else fades), the node in focus,
   *  and the kinds hidden. Applied to the drawn graph in place, without a new layout. */
  traced?: ReadonlySet<string> | null;
  focus?: string | null;
  hiddenKinds?: ReadonlySet<string>;
  /** Extra controls for the bar, such as the explorer's search. */
  toolbar?: ReactNode;
}

const NO_KINDS: ReadonlySet<string> = new Set();

export function GraphView({
  elements,
  highlight,
  truncated = false,
  onSelect,
  height = 460,
  traced = null,
  focus = null,
  hiddenKinds = NO_KINDS,
  toolbar,
}: GraphViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [asTable, setAsTable] = useState(false);
  const [drawFailed, setDrawFailed] = useState(false);
  const [drawn, setDrawn] = useState(0); // bumps each time a canvas is created
  const fitted = useRef(false);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const marked = useMemo(() => {
    const ids = new Set(highlight ?? []);
    for (const e of elements) if (e.classes.split(" ").includes("highlight")) ids.add(e.data.id);
    return ids;
  }, [highlight, elements]);
  const kindOf = useMemo(
    () =>
      new Map(elements.filter((e) => e.group === "nodes").map((n) => [n.data.id, n.data.label])),
    [elements],
  );
  const isHidden = (e: GraphElement) =>
    e.group === "nodes"
      ? hiddenKinds.has(e.data.label)
      : hiddenKinds.has(kindOf.get(e.data.source ?? "") ?? "") ||
        hiddenKinds.has(kindOf.get(e.data.target ?? "") ?? "");
  const nodes = elements.filter((e) => e.group === "nodes" && !isHidden(e));
  const edges = elements.filter((e) => e.group === "edges" && !isHidden(e));
  const showTable = asTable || drawFailed;
  const themeVersion = useThemeVersion();
  const total = elements.filter((e) => e.group === "nodes").length;

  useEffect(() => {
    if (showTable || !container.current) return;
    let instance: Core;
    try {
      instance = cytoscape({
        container: container.current,
        elements: elements.map((e) => ({ group: e.group, data: e.data, classes: e.classes })),
        style: stylesheet(),
        wheelSensitivity: 0.3,
      });
    } catch {
      setDrawFailed(true); // no canvas (old browser or a test environment): show the table
      return;
    }
    cy.current = instance;
    // Framing a node waits for the layout to settle: fitted earlier, it would frame the spot
    // the nodes started at, and the graph would be drawn out of view.
    const layout = instance.layout(
      total < 150
        ? {
            name: "cose",
            animate: !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
            animationDuration: 500,
            padding: 30,
            nodeRepulsion: () => 9000,
            idealEdgeLength: () => 70,
          }
        : { name: "breadthfirst", directed: true, padding: 30 },
    );
    layout.one("layoutstop", () => {
      fitted.current = false;
      setDrawn((n) => n + 1);
    });
    layout.run();
    instance.on("tap", "node, edge", (event) => {
      const id = event.target.id();
      const element = elements.find((e) => e.data.id === id);
      if (element) selectRef.current?.(element);
    });
    return () => {
      instance.destroy();
      cy.current = null;
    };
  }, [elements, showTable, total, themeVersion]);

  // Highlight, trace, filters and focus, applied to the drawn graph in place.
  useEffect(() => {
    const instance = cy.current;
    if (!instance) return;
    instance.batch(() => {
      instance.elements().forEach((el) => {
        const id = el.id();
        const kind = (of: unknown) => kindOf.get(String(of)) ?? "";
        const ends: unknown[] =
          el.group() === "nodes" ? [id] : [el.data("source"), el.data("target")];
        el.toggleClass("highlight", marked.has(id));
        el.toggleClass("traced", !!traced && traced.has(id));
        el.toggleClass("faded", !!traced && !traced.has(id) && id !== focus);
        el.toggleClass("focus", id === focus);
        el.toggleClass(
          "hidden",
          ends.some((end) => hiddenKinds.has(kind(end))),
        );
      });
    });
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const show = (eles: cytoscape.CollectionReturnValue, padding: number) =>
      still
        ? instance.fit(eles, padding)
        : instance.animate({ fit: { eles, padding } }, { duration: 300 });
    const target = focus ? instance.getElementById(focus) : null;
    if (target?.nonempty()) {
      show(traced ? instance.$(".traced, .focus") : target.closedNeighborhood(), 50);
    } else if (!fitted.current) {
      const lit = instance.$(".highlight");
      if (lit.nonempty()) instance.fit(lit.closedNeighborhood(), 40);
    }
    fitted.current = true;
  }, [drawn, marked, traced, focus, hiddenKinds, kindOf]);

  const zoom = (factor: number) => {
    const instance = cy.current;
    if (!instance) return;
    instance.animate(
      {
        zoom: {
          level: instance.zoom() * factor,
          position: { x: instance.width() / 2, y: instance.height() / 2 },
        },
      },
      { duration: 180 },
    );
  };
  const fit = () =>
    cy.current?.animate({ fit: { eles: cy.current.elements(), padding: 30 } }, { duration: 250 });

  const isLit = (e: GraphElement) => marked.has(e.data.id) || (!!traced && traced.has(e.data.id));
  const rows = traced ? nodes.filter((n) => traced.has(n.data.id) || n.data.id === focus) : nodes;
  const edgeRows = traced ? edges.filter((e) => traced.has(e.data.id)) : edges;

  return (
    <Card className="graph" aria-label="Authority graph">
      <div className="graph-bar">
        <Network size={15} aria-hidden="true" />
        <span>
          {nodes.length} nodes · {edges.length} edges
          {truncated && " · truncated: the decision log was cut first"}
        </span>
        <span className="spacer" />
        {toolbar}
        {!showTable && (
          <>
            <Tip content="Zoom in">
              <button
                type="button"
                className="ghost icon sm"
                aria-label="Zoom in"
                onClick={() => zoom(1.25)}
              >
                <ZoomIn size={15} aria-hidden="true" />
              </button>
            </Tip>
            <Tip content="Zoom out">
              <button
                type="button"
                className="ghost icon sm"
                aria-label="Zoom out"
                onClick={() => zoom(0.8)}
              >
                <ZoomOut size={15} aria-hidden="true" />
              </button>
            </Tip>
            <Tip content="Fit to view">
              <button
                type="button"
                className="ghost icon sm"
                aria-label="Fit to view"
                onClick={fit}
              >
                <Maximize2 size={15} aria-hidden="true" />
              </button>
            </Tip>
          </>
        )}
        {!drawFailed && (
          <button type="button" className="sm" onClick={() => setAsTable((v) => !v)}>
            {asTable ? (
              <Network size={14} aria-hidden="true" />
            ) : (
              <Table2 size={14} aria-hidden="true" />
            )}
            {asTable ? "Show as graph" : "Show as table"}
          </button>
        )}
      </div>
      {nodes.length === 0 && (
        <p className="muted" style={{ padding: "12px 14px" }}>
          Nothing here yet: no rules or decisions.
        </p>
      )}
      {showTable ? (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Graph nodes</caption>
            <thead>
              <tr>
                <th scope="col">Kind</th>
                <th scope="col">What</th>
                <th scope="col">State</th>
                <th scope="col">Id</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((n) => (
                <tr key={n.data.id} className={isLit(n) || n.data.id === focus ? "lit" : undefined}>
                  <td>{n.data.label}</td>
                  <td>
                    {onSelect ? (
                      <button type="button" className="link" onClick={() => onSelect(n)}>
                        {n.data.caption ?? n.data.id}
                      </button>
                    ) : (
                      (n.data.caption ?? n.data.id)
                    )}
                    {n.data.id === focus ? (
                      <span className="chip flag-info">traced from here</span>
                    ) : (
                      isLit(n) && <span className="chip flag-info">on the path</span>
                    )}
                  </td>
                  <td>
                    {n.classes
                      .split(" ")
                      .filter((c) => c !== n.data.label.toLowerCase() && c !== "highlight")
                      .join(", ")}
                  </td>
                  <td className="mono">{n.data.id}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table>
            <caption className="sr-only">Graph edges</caption>
            <thead>
              <tr>
                <th scope="col">From</th>
                <th scope="col">Relationship</th>
                <th scope="col">To</th>
              </tr>
            </thead>
            <tbody>
              {edgeRows.map((e) => (
                <tr key={e.data.id} className={isLit(e) ? "lit" : undefined}>
                  <td className="mono">{e.data.source}</td>
                  <td>
                    {e.data.label}
                    {e.classes.includes("untrusted") && " (from untrusted content)"}
                    {e.classes.includes("revoked") && " (revoked)"}
                  </td>
                  <td className="mono">{e.data.target}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div ref={container} className="graph-canvas" style={{ height }} />
      )}
      {!showTable && nodes.length > 0 && (
        <div className="legend" aria-hidden="true">
          <span>
            <i className="swatch" style={{ background: "var(--accent)", borderRadius: 99 }} />{" "}
            principal
          </span>
          <span>
            <i className="swatch" style={{ background: "var(--agent)" }} /> agent
          </span>
          <span>
            <i className="swatch" style={{ background: "var(--allow)" }} /> allowed
          </span>
          <span>
            <i className="swatch" style={{ background: "var(--confirm)" }} /> needs approval
          </span>
          <span>
            <i className="swatch" style={{ background: "var(--deny)" }} /> denied
          </span>
          <span>
            <i className="swatch" style={{ background: "var(--quarantine)" }} /> quarantined
          </span>
          <span>
            <i className="swatch" style={{ border: "1px dashed var(--muted)" }} /> untrusted origin
          </span>
        </div>
      )}
    </Card>
  );
}
