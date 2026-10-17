// Exploring the authority graph without drawing it: search, the kinds present, a node's
// neighbours, and its lineage traced both ways. Pure, so the explorer's answers are the same
// on the canvas and in the table view, and testable without a canvas.

import type { GraphElement } from "./types";

/** The node kinds, in the order authority flows: who said what, the rule it became, the agent
 *  that acted, and how that was decided. */
export const KINDS = [
  "Principal",
  "Utterance",
  "Summary",
  "Instruction",
  "Scope",
  "Agent",
  "Action",
  "Decision",
  "Approval",
] as const;

export const KIND_WORDS: Record<string, string> = {
  Principal: "People",
  Utterance: "Things said",
  Summary: "Summaries",
  Instruction: "Rules",
  Scope: "Scopes",
  Agent: "Agents",
  Action: "Actions",
  Decision: "Decisions",
  Approval: "Approvals",
};

export interface Lineage {
  /** Everything the node came from: the rules, sayings and people behind it. */
  up: Set<string>;
  /** Everything that came from it: the actions and decisions it led to. */
  down: Set<string>;
  /** The edges walked, both ways. */
  edges: Set<string>;
}

const nodesOf = (elements: GraphElement[]) => elements.filter((e) => e.group === "nodes");
const edgesOf = (elements: GraphElement[]) => elements.filter((e) => e.group === "edges");

/** How many nodes of each kind, in flow order; kinds with none are left out. */
export function kindCounts(elements: GraphElement[]): { kind: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const node of nodesOf(elements)) {
    counts.set(node.data.label, (counts.get(node.data.label) ?? 0) + 1);
  }
  const known = KINDS.filter((k) => counts.has(k)).map((kind) => ({
    kind,
    count: counts.get(kind)!,
  }));
  const other = [...counts.keys()]
    .filter((k) => !(KINDS as readonly string[]).includes(k))
    .sort()
    .map((kind) => ({ kind, count: counts.get(kind)! }));
  return [...known, ...other];
}

function haystack(node: GraphElement): string {
  const { id, label, caption, ...rest } = node.data;
  const extra = Object.values(rest).filter((v) => typeof v === "string");
  return [id, label, caption ?? "", ...extra].join(" ").toLowerCase();
}

/** Nodes whose id, caption or text holds every word of ``query``; captions that start with
 *  the query come first. At most ``limit``. */
export function searchNodes(elements: GraphElement[], query: string, limit = 8): GraphElement[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  const q = query.trim().toLowerCase();
  const scored = nodesOf(elements)
    .filter((node) => {
      const text = haystack(node);
      return words.every((w) => text.includes(w));
    })
    .map((node) => {
      const caption = (node.data.caption ?? "").toLowerCase();
      const rank = node.data.id.toLowerCase() === q ? 0 : caption.startsWith(q) ? 1 : 2;
      return { node, rank };
    });
  scored.sort(
    (a, b) =>
      a.rank - b.rank ||
      KINDS.indexOf(a.node.data.label as never) - KINDS.indexOf(b.node.data.label as never),
  );
  return scored.slice(0, limit).map((s) => s.node);
}

/** A node's direct neighbours: what points to it, and what it points to, with the edge. */
export function neighbours(
  elements: GraphElement[],
  id: string,
): {
  incoming: { edge: GraphElement; node: GraphElement }[];
  outgoing: { edge: GraphElement; node: GraphElement }[];
} {
  const byId = new Map(nodesOf(elements).map((n) => [n.data.id, n]));
  const incoming: { edge: GraphElement; node: GraphElement }[] = [];
  const outgoing: { edge: GraphElement; node: GraphElement }[] = [];
  for (const edge of edgesOf(elements)) {
    if (edge.data.target === id && byId.has(edge.data.source!)) {
      incoming.push({ edge, node: byId.get(edge.data.source!)! });
    }
    if (edge.data.source === id && byId.has(edge.data.target!)) {
      outgoing.push({ edge, node: byId.get(edge.data.target!)! });
    }
  }
  return { incoming, outgoing };
}

/** Which way authority flows along each relationship: "forward" when the edge points from
 *  cause to effect (a person SAID a sentence), "back" when it points from effect to cause (a
 *  decision USED a rule). Context edges (a rule APPLIES_TO an agent, is ABOUT a scope) are shown
 *  one hop from the traced node but never walked through: an agent's other rules are not part
 *  of one decision's lineage. */
const FLOW: Record<string, "forward" | "back"> = {
  SAID: "forward",
  EXPRESSES: "forward",
  DERIVED_FROM: "back",
  SUPERSEDES: "back",
  DELEGATES_TO: "forward",
  APPLIES_TO: "forward",
  ABOUT: "forward",
  PROPOSED_BY: "back",
  CHECKED: "back",
  USED: "back",
  APPROVES: "forward",
};
const CONTEXT = new Set(["APPLIES_TO", "ABOUT"]);

/** The node's lineage: every node it came from (walked against the flow of authority) and
 *  every node it led to (walked with it), each separately so a sibling's lineage is not
 *  pulled in. */
export function traceLineage(elements: GraphElement[], id: string): Lineage {
  // cause -> [effects] and effect -> [causes], each with the edge that joins them.
  const effects = new Map<string, { edge: GraphElement; node: string }[]>();
  const causes = new Map<string, { edge: GraphElement; node: string }[]>();
  const add = (map: typeof effects, key: string, value: { edge: GraphElement; node: string }) => {
    const list = map.get(key);
    if (list) list.push(value);
    else map.set(key, [value]);
  };
  for (const edge of edgesOf(elements)) {
    const { source, target, label } = edge.data;
    if (!source || !target) continue;
    const [cause, effect] = FLOW[label] === "back" ? [target, source] : [source, target];
    add(effects, cause, { edge, node: effect });
    add(causes, effect, { edge, node: cause });
  }
  const edges = new Set<string>();
  const walk = (step: typeof effects) => {
    const seen = new Set<string>();
    const queue = [id];
    while (queue.length > 0) {
      const current = queue.shift()!;
      for (const { edge, node } of step.get(current) ?? []) {
        const context = CONTEXT.has(edge.data.label);
        if (context && current !== id) continue;
        edges.add(edge.data.id);
        if (node === id || seen.has(node)) continue;
        seen.add(node);
        if (!context) queue.push(node);
      }
    }
    return seen;
  };
  return { up: walk(causes), down: walk(effects), edges };
}

/** The properties worth showing for a node, as label/value pairs, timestamps as dates. */
export function describeNode(node: GraphElement): { key: string; value: string }[] {
  const skip = new Set(["id", "label", "caption"]);
  return Object.entries(node.data)
    .filter(
      ([key, value]) => !skip.has(key) && value !== null && value !== undefined && value !== "",
    )
    .map(([key, value]) => ({
      key: key.replaceAll("_", " "),
      value:
        typeof value === "number" && (key === "at" || key.endsWith("_at") || key === "as_of")
          ? new Date(value).toLocaleString()
          : typeof value === "boolean"
            ? value
              ? "yes"
              : "no"
            : String(value),
    }));
}
