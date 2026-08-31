/**
 * Per-dialect session routing state.
 *
 * This is the TS value-side equivalent of Python3
 * `l2.shells.session.ShellSession`. It contains only frontend routing state:
 * mode, cell, agent and protocol session identity. It never owns an AgentLoop,
 * Cell, terminal process, cursor, outbox, or capability.
 */

export type ShellMode = "L3A" | "DIRECT";

export interface ShellSessionSnapshot {
  shell: string;
  mode: ShellMode;
  cell_id: string;
  agent_id: string;
  session_id: string;
}

export interface ShellSessionOptions {
  shell?: string;
  mode?: ShellMode;
  cellId?: string;
  agentId?: string;
  sessionId?: string;
}

export class ShellSession {
  public shell: string;
  public mode: ShellMode;
  public cell_id: string;
  public agent_id: string;
  public session_id: string;

  constructor(options: ShellSessionOptions = {}) {
    this.shell = options.shell ?? "";
    this.mode = options.mode ?? "L3A";
    this.cell_id = options.cellId ?? "";
    this.agent_id = options.agentId ?? "";
    this.session_id = options.sessionId ?? "";
    if (this.mode === "DIRECT" && !this.agent_id) this.mode = "L3A";
  }

  /** Whether a concrete agent target is available for direct tool requests. */
  isDirect(): boolean {
    return this.mode === "DIRECT" && this.agent_id.length > 0;
  }

  /** Switch this routing view to one concrete Cell/Agent target. */
  switchToDirect(cellId: string, agentId: string, sessionId = this.session_id): void {
    this.mode = "DIRECT";
    this.cell_id = cellId;
    this.agent_id = agentId;
    this.session_id = sessionId;
  }

  /** Return to L3A natural-language routing and clear the direct target. */
  switchToL3A(): void {
    this.mode = "L3A";
    this.agent_id = "";
    this.session_id = "";
  }

  /** Return a detached, JSON-safe snapshot for a frontend or diagnostic view. */
  asDict(): ShellSessionSnapshot {
    return {
      shell: this.shell,
      mode: this.mode,
      cell_id: this.cell_id,
      agent_id: this.agent_id,
      session_id: this.session_id,
    };
  }
}
