export type Clip = { text: string; truncated: boolean; full_length: number };

export type Usage = {
  agents: Record<
    string,
    { model: string; tier: string; input: number; output: number; cost: number }
  >;
  total_cost_usd: number;
};

export type TraceEvent =
  | { kind: "run_started"; ts: number; provider: string; models: Record<string, string> }
  | { kind: "stage"; ts: number; agent: string }
  | {
      kind: "agent_prompt";
      ts: number;
      agent: string;
      model: string;
      tier: string;
      system: Clip;
      turns: number;
      tools: string[];
      state_keys: string[];
    }
  | {
      kind: "agent_output";
      ts: number;
      agent: string;
      model: string;
      tier: string;
      content: Clip;
      tokens: { input: number; output: number };
      cost_usd: number;
      elapsed_s: number;
    }
  | { kind: "tool_call"; ts: number; agent: string; tool: string; args: unknown }
  | { kind: "tool_result"; ts: number; agent: string; tool: string; args?: unknown; result: unknown }
  | {
      kind: "result";
      ts: number;
      document: string;
      itinerary: unknown;
      profile: unknown;
      deterministic: DeterministicReport | null;
      reviewer: ReviewerReport | null;
      usage: Usage;
    }
  | { kind: "error"; ts: number; message: string }
  | { kind: "done" };

export type Issue = {
  severity: "critical" | "warning";
  code: string;
  day: number | null;
  message: string;
};

export type DeterministicReport = {
  passed: boolean;
  issues: Issue[];
  computed: Record<string, number | string>;
};

export type ReviewerReport = { passed: boolean; issues: Issue[]; notes?: string };

export type ChatMessage = {
  role: "user" | "agent" | "system";
  text: string;
  /** "warn" marks a run that finished with unresolved critical problems. */
  tone?: "warn";
  pending?: boolean;
};

/** One agent's activity, folded from the raw event stream. */
export type AgentTrace = {
  name: string;
  tier: string;
  model: string;
  prompt?: Clip;
  tools: { tool: string; args: unknown; result?: unknown }[];
  outputs: Clip[];
  tokens: { input: number; output: number };
  cost: number;
  elapsed: number;
  status: "running" | "done";
  stateKeys: string[];
  declaredTools: string[];
};
