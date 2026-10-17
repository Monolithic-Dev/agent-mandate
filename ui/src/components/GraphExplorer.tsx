// The graph explorer: find a node by what it says, hide the kinds you are not looking at, and
// trace a node's lineage both ways: the people, sayings and rules it came from, and the
// actions and decisions it led to. The inspector beside the graph names every neighbour, so
// the same exploring works from the keyboard and the table view. The node in focus and the
// trace are kept in the address, so a traced view can be shared as a link.

import { ArrowDownRight, ArrowUpLeft, Crosshair, ExternalLink, Route, Search, X } from "../icons";
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  describeNode,
  KIND_WORDS,
  kindCounts,
  neighbours,
  searchNodes,
  traceLineage,
} from "../graphExplore";
import type { GraphElement } from "../types";
import { GraphView } from "./GraphView";

const LIST_LIMIT = 12;

function pageOf(tid: string, node: GraphElement): string | null {
  if (node.data.label === "Decision") return `/tenants/${tid}/decisions/${node.data.id}`;
  if (node.data.label === "Instruction") return `/tenants/${tid}/instructions/${node.data.id}`;
  return null;
}

function NodeButton({ node, onPick }: { node: GraphElement; onPick: (id: string) => void }) {
  return (
    <button type="button" className="node-pick" onClick={() => onPick(node.data.id)}>
      <span className={`kind-dot kind-${node.data.label.toLowerCase()}`} aria-hidden="true" />
      <span className="node-pick-text">{node.data.caption ?? node.data.id}</span>
      <span className="muted small">{KIND_WORDS[node.data.label] ?? node.data.label}</span>
    </button>
  );
}

function NodeList({
  title,
  icon: Icon,
  nodes,
  onPick,
}: {
  title: string;
  icon: typeof ArrowUpLeft;
  nodes: GraphElement[];
  onPick: (id: string) => void;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? nodes : nodes.slice(0, LIST_LIMIT);
  return (
    <section className="inspector-list" aria-label={title}>
      <h4>
        <Icon size={13} aria-hidden="true" /> {title} <span className="count">{nodes.length}</span>
      </h4>
      {nodes.length === 0 ? (
        <p className="muted small">Nothing.</p>
      ) : (
        <ul>
          {shown.map((node) => (
            <li key={node.data.id}>
              <NodeButton node={node} onPick={onPick} />
            </li>
          ))}
        </ul>
      )}
      {nodes.length > LIST_LIMIT && (
        <button type="button" className="link small" onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show all ${nodes.length}`}
        </button>
      )}
    </section>
  );
}

export function GraphExplorer({
  tid,
  elements,
  truncated,
  height = 560,
}: {
  tid: string;
  elements: GraphElement[];
  truncated: boolean;
  height?: number;
}) {
  const [params, setParams] = useSearchParams();
  const focusId = params.get("node");
  const tracing = params.get("trace") === "1";
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set(["Scope"]));
  const searchRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  const byId = useMemo(
    () => new Map(elements.filter((e) => e.group === "nodes").map((n) => [n.data.id, n])),
    [elements],
  );
  const focus = focusId ? (byId.get(focusId) ?? null) : null;
  const kinds = useMemo(() => kindCounts(elements), [elements]);
  const results = useMemo(() => searchNodes(elements, query), [elements, query]);
  const lineage = useMemo(
    () => (focus && tracing ? traceLineage(elements, focus.data.id) : null),
    [elements, focus, tracing],
  );
  const traced = useMemo(
    () => (lineage ? new Set([...lineage.up, ...lineage.down, ...lineage.edges]) : null),
    [lineage],
  );
  const near = useMemo(
    () => (focus ? neighbours(elements, focus.data.id) : null),
    [elements, focus],
  );

  const update = (changes: Record<string, string | null>) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null) next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  const pick = (id: string, trace = tracing) => {
    const kind = byId.get(id)?.data.label;
    if (kind && hidden.has(kind)) {
      setHidden((current) => new Set([...current].filter((k) => k !== kind)));
    }
    update({ node: id, trace: trace ? "1" : null });
    setOpen(false);
    setQuery("");
  };
  const clear = () => update({ node: null, trace: null });

  // A link straight to a node of a kind that is hidden shows that kind.
  const focusKind = focus?.data.label;
  useEffect(() => {
    if (focusKind)
      setHidden((current) =>
        current.has(focusKind) ? new Set([...current].filter((k) => k !== focusKind)) : current,
      );
  }, [focusKind]);

  // "/" jumps to the search, as on most consoles; Escape leaves the focused node.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
      if (event.key === "/" && !typing && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(results.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (event.key === "Enter" && results[active]) {
      event.preventDefault();
      pick(results[active].data.id);
    } else if (event.key === "Escape") {
      if (query) setQuery("");
      else setOpen(false);
    }
  };

  const toggleKind = (kind: string) =>
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  const nodesIn = (ids: Set<string>) =>
    [...ids].map((id) => byId.get(id)).filter((n): n is GraphElement => !!n);
  const page = focus ? pageOf(tid, focus) : null;

  const search = (
    <div className="graph-search" role="search">
      <Search size={14} aria-hidden="true" />
      <input
        ref={searchRef}
        type="search"
        placeholder="Find a node…"
        aria-label="Find a node in the graph"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && results[active] ? `${listId}-${active}` : undefined}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onSearchKey}
      />
      {open && query && (
        <ul id={listId} role="listbox" className="graph-results" aria-label="Matching nodes">
          {results.length === 0 && (
            <li className="muted small graph-results-none" role="presentation">
              No node matches “{query}”.
            </li>
          )}
          {results.map((node, index) => (
            <li
              key={node.data.id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className={index === active ? "active" : undefined}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActive(index)}
              onClick={() => pick(node.data.id)}
            >
              <span
                className={`kind-dot kind-${node.data.label.toLowerCase()}`}
                aria-hidden="true"
              />
              <span className="node-pick-text">{node.data.caption ?? node.data.id}</span>
              <span className="muted small">{KIND_WORDS[node.data.label] ?? node.data.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  return (
    <div className={`explorer${focus ? " has-focus" : ""}`}>
      <div className="kind-filters" role="group" aria-label="Show or hide kinds of node">
        {kinds.map(({ kind, count }) => {
          const on = !hidden.has(kind);
          return (
            <button
              key={kind}
              type="button"
              className={`kind-chip${on ? " on" : ""}`}
              aria-pressed={on}
              onClick={() => toggleKind(kind)}
            >
              <span className={`kind-dot kind-${kind.toLowerCase()}`} aria-hidden="true" />
              {KIND_WORDS[kind] ?? kind}
              <span className="muted">{count}</span>
            </button>
          );
        })}
      </div>
      <div className="explorer-body">
        <GraphView
          elements={elements}
          truncated={truncated}
          height={height}
          traced={traced}
          focus={focus?.data.id ?? null}
          hiddenKinds={hidden}
          onSelect={(element) => {
            if (element.group === "nodes") pick(element.data.id);
          }}
          toolbar={search}
        />
        <aside className="inspector card" aria-label="Selected node" aria-live="polite">
          {!focus ? (
            <div className="inspector-empty">
              <Crosshair size={22} aria-hidden="true" />
              <p>
                <strong>Pick a node</strong> on the graph, or find one with the search (press{" "}
                <kbd className="kbd">/</kbd>).
              </p>
              <p className="muted small">
                Then trace its lineage: who said what, the rule it became, and every action and
                decision it led to.
              </p>
            </div>
          ) : (
            <>
              <div className="inspector-head">
                <span
                  className={`kind-dot kind-${focus.data.label.toLowerCase()}`}
                  aria-hidden="true"
                />
                <span className="eyebrow">{KIND_WORDS[focus.data.label] ?? focus.data.label}</span>
                <span className="spacer" />
                <button
                  type="button"
                  className="ghost icon sm"
                  aria-label="Clear the selection"
                  onClick={clear}
                >
                  <X size={15} aria-hidden="true" />
                </button>
              </div>
              <h3 className="inspector-title">{focus.data.caption ?? focus.data.id}</h3>
              <p className="mono small muted">{focus.data.id}</p>
              <div className="inspector-actions">
                <button
                  type="button"
                  className={tracing ? "primary sm" : "sm"}
                  aria-pressed={tracing}
                  onClick={() => update({ trace: tracing ? null : "1" })}
                >
                  <Route size={14} aria-hidden="true" />
                  {tracing ? "Stop tracing" : "Trace lineage"}
                </button>
                {page && (
                  <Link to={page} className="btn sm">
                    <ExternalLink size={14} aria-hidden="true" /> Open
                  </Link>
                )}
              </div>
              <dl className="inspector-props">
                {describeNode(focus).map(({ key, value }) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
              {lineage ? (
                <>
                  <p className="small trace-sum">
                    Traced: <strong>{lineage.up.size}</strong> it came from,{" "}
                    <strong>{lineage.down.size}</strong> it led to.
                  </p>
                  <NodeList
                    title="Came from"
                    icon={ArrowUpLeft}
                    nodes={nodesIn(lineage.up)}
                    onPick={pick}
                  />
                  <NodeList
                    title="Led to"
                    icon={ArrowDownRight}
                    nodes={nodesIn(lineage.down)}
                    onPick={pick}
                  />
                </>
              ) : (
                near && (
                  <>
                    <NodeList
                      title="Points here"
                      icon={ArrowUpLeft}
                      nodes={near.incoming.map((n) => n.node)}
                      onPick={pick}
                    />
                    <NodeList
                      title="Points to"
                      icon={ArrowDownRight}
                      nodes={near.outgoing.map((n) => n.node)}
                      onPick={pick}
                    />
                  </>
                )
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
