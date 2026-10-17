import { describe, expect, it } from "vitest";

import { describeNode, kindCounts, neighbours, searchNodes, traceLineage } from "./graphExplore";
import type { GraphElement } from "./types";

const node = (id: string, label: string, caption: string, extra = {}): GraphElement => ({
  group: "nodes",
  data: { id, label, caption, ...extra },
  classes: label.toLowerCase(),
});
const edge = (source: string, label: string, target: string): GraphElement => ({
  group: "edges",
  data: { id: `${source}>${label}>${target}`, source, target, label },
  classes: label.toLowerCase(),
});

// Dana said two things; each became a rule for the same agent. The agent's one action was
// decided on the first rule alone.
const GRAPH: GraphElement[] = [
  node("prn_1", "Principal", "Dana (owner)"),
  node("utt_1", "Utterance", "You may read my email", { text: "You may read my email." }),
  node("utt_2", "Utterance", "Archive newsletters"),
  node("ins_1", "Instruction", "allow: read my email", { effect: "allow", activated_at: 0 }),
  node("ins_2", "Instruction", "allow: archive newsletters"),
  node("scp_1", "Scope", "email.read on inbox/*"),
  node("agt_1", "Agent", "main (primary)"),
  node("act_1", "Action", "email.read inbox/m-1"),
  node("dec_1", "Decision", "ALLOW: authorized"),
  edge("prn_1", "SAID", "utt_1"),
  edge("prn_1", "SAID", "utt_2"),
  edge("utt_1", "EXPRESSES", "ins_1"),
  edge("utt_2", "EXPRESSES", "ins_2"),
  edge("ins_1", "ABOUT", "scp_1"),
  edge("ins_1", "APPLIES_TO", "agt_1"),
  edge("ins_2", "APPLIES_TO", "agt_1"),
  edge("act_1", "PROPOSED_BY", "agt_1"),
  edge("dec_1", "CHECKED", "act_1"),
  edge("dec_1", "USED", "ins_1"),
];

const sorted = (ids: Set<string>) => [...ids].sort();

describe("traceLineage", () => {
  it("traces a decision back to the rule it used and who said it, not the agent's other rules", () => {
    const { up, down } = traceLineage(GRAPH, "dec_1");
    expect(sorted(up)).toEqual(["act_1", "agt_1", "ins_1", "prn_1", "utt_1"]);
    expect(down.size).toBe(0);
  });

  it("traces a rule both ways: where it came from, and the decisions that used it", () => {
    const { up, down, edges } = traceLineage(GRAPH, "ins_1");
    expect(sorted(up)).toEqual(["prn_1", "utt_1"]);
    // Its scope and agent are shown one hop out; the agent's actions are not its doing.
    expect(sorted(down)).toEqual(["agt_1", "dec_1", "scp_1"]);
    expect(edges.has("dec_1>USED>ins_1")).toBe(true);
    expect(edges.has("act_1>PROPOSED_BY>agt_1")).toBe(false);
  });

  it("traces a person forward to everything their words became", () => {
    const { up, down } = traceLineage(GRAPH, "prn_1");
    expect(up.size).toBe(0);
    expect(sorted(down)).toEqual(["dec_1", "ins_1", "ins_2", "utt_1", "utt_2"]);
  });

  it("does not loop on a cycle", () => {
    const cyclic = [
      node("a", "Agent", "a"),
      node("b", "Agent", "b"),
      edge("a", "DELEGATES_TO", "b"),
      edge("b", "DELEGATES_TO", "a"),
    ];
    const { up, down } = traceLineage(cyclic, "a");
    expect(sorted(up)).toEqual(["b"]);
    expect(sorted(down)).toEqual(["b"]);
  });
});

describe("searchNodes", () => {
  it("matches every word, in captions, ids and text, best first", () => {
    expect(searchNodes(GRAPH, "email read").map((n) => n.data.id)).toEqual([
      "utt_1",
      "ins_1",
      "scp_1",
      "act_1",
    ]);
    expect(searchNodes(GRAPH, "dec_1")[0].data.id).toBe("dec_1");
    expect(searchNodes(GRAPH, "  ")).toEqual([]);
    expect(searchNodes(GRAPH, "nothing like this")).toEqual([]);
  });
});

describe("kindCounts and neighbours", () => {
  it("counts kinds in the order authority flows", () => {
    expect(kindCounts(GRAPH).map((k) => `${k.kind}:${k.count}`)).toEqual([
      "Principal:1",
      "Utterance:2",
      "Instruction:2",
      "Scope:1",
      "Agent:1",
      "Action:1",
      "Decision:1",
    ]);
  });

  it("names a node's direct neighbours each way", () => {
    const { incoming, outgoing } = neighbours(GRAPH, "agt_1");
    expect(incoming.map((n) => n.node.data.id).sort()).toEqual(["act_1", "ins_1", "ins_2"]);
    expect(outgoing).toEqual([]);
  });

  it("describes a node's properties in words, times as dates", () => {
    const props = describeNode(GRAPH[3]);
    expect(props.map((p) => p.key)).toEqual(["effect", "activated at"]);
    expect(props[1].value).toBe(new Date(0).toLocaleString());
  });
});
