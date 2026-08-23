/**
 * Selector projection — local rendering of cell/agent selection data.
 *
 * Mirrors the Python3 selector surface (src/l2/selector.py) as a pure
 * projection: the TS side consumes reachability/roster dicts from the host
 * (via bridge cell_liveness) and renders selection candidates. It never
 * owns liveness authority and leaks zero object handles — every value is a
 * plain dict, matching the Python3 post-P1 dict-data API.
 */

/** One agent's roster entry as delivered by the host liveness dict. */
export interface AgentRosterEntry {
  cell_id: string;
  agent_id: string;
  role: string;
  status: string;
  alive: boolean;
  territory: string[];
}

/** preselect() result shape (mirrors src/l2/selector.py preselect). */
export interface PreselectResult {
  agents: AgentRosterEntry[];
  cells: string[];
  total: number;
  error?: string;
}

/** select() result shape (mirrors src/l2/selector.py select). */
export interface SelectResult {
  success: boolean;
  cell_id: string;
  agent_id: string;
  identity: Record<string, unknown> | null;
  error: string;
}

/** Normalize a raw host liveness dict into roster entries (pure). */
export function toRoster(liveness: Record<string, unknown>): AgentRosterEntry[] {
  const entries: AgentRosterEntry[] = [];
  const agents = (liveness.agents as Record<string, Record<string, unknown>> | undefined) ?? {};
  const territory = Array.isArray(liveness.territory) ? (liveness.territory as string[]) : [];
  for (const [agentId, info] of Object.entries(agents)) {
    entries.push({
      cell_id: String(liveness.cell_id ?? ""),
      agent_id: agentId,
      role: String(info.role ?? info.status ?? "?"),
      status: String(info.status ?? "unknown"),
      alive: Boolean(info.alive),
      territory,
    });
  }
  return entries;
}

/** Build the preselect projection from per-cell liveness dicts (pure). */
export function preselect(cells: Record<string, Record<string, unknown>>): PreselectResult {
  const agents: AgentRosterEntry[] = [];
  const cellIds: string[] = [];
  for (const [cellId, liveness] of Object.entries(cells)) {
    cellIds.push(cellId);
    agents.push(...toRoster({ ...liveness, cell_id: cellId }));
  }
  return { agents, cells: cellIds, total: agents.length };
}

/** Select by agent id across the roster (pure, O(n); role index optional). */
export function selectByAgentId(roster: AgentRosterEntry[], agentId: string): SelectResult {
  const found = roster.find((a) => a.agent_id === agentId);
  if (!found) {
    return { success: false, cell_id: "", agent_id: agentId, identity: null, error: `unknown agent: ${agentId}` };
  }
  return { success: true, cell_id: found.cell_id, agent_id: found.agent_id, identity: { ...found }, error: "" };
}

/** Select the first matching role (case-insensitive) in a cell/domain. */
export function selectByRole(
  roster: AgentRosterEntry[],
  role: string,
  cellId = "",
  domain = "",
): SelectResult {
  const lower = role.toLowerCase();
  const match =
    roster.find(
      (a) =>
        a.role.toLowerCase() === lower &&
        (!cellId || a.cell_id === cellId) &&
        (!domain || a.territory.includes(domain)),
    ) ?? roster.find((a) => a.role.toLowerCase() === lower && (!cellId || a.cell_id === cellId));
  if (!match) {
    return { success: false, cell_id: cellId, agent_id: "", identity: null, error: `no agent for role: ${role}` };
  }
  return { success: true, cell_id: match.cell_id, agent_id: match.agent_id, identity: { ...match }, error: "" };
}
