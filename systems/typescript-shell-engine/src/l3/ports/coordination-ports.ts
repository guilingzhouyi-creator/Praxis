/**
 * Explicit data ports for TypeScript L3 card and scheduler coordination.
 *
 * The `typescript` authority label means only that L3 owns the request
 * orchestration. Any process, terminal, capability, or hard-constraint work
 * still belongs to the Rust execution port.
 */

export type {
  CardIntent,
  CardIntentPort,
  CardIntentReceipt,
  CardIntentAction,
  CardIntentOperation,
  CardLifecycleHint,
  CardLinkProjection,
} from "../card/card-coordination.ts";

export type {
  ScheduleRequest,
  ScheduleRequestAction,
  ScheduleRequestPort,
  ScheduleReceipt,
  ScheduleScope,
} from "../scheduler/scheduler-coordination.ts";

import type { CardIntentPort } from "../card/card-coordination.ts";
import type { ScheduleRequestPort } from "../scheduler/scheduler-coordination.ts";

/** Independently injectable Card/Scheduler ports used by AgentRuntime. */
export interface L3CoordinationPorts {
  readonly card?: CardIntentPort;
  readonly scheduler?: ScheduleRequestPort;
}
