/**
 * Aggregate-only input activity projection for the Rust/TS boundary.
 *
 * Host adapters inject observations; this module never reads device nodes,
 * parses key values, stores pointer coordinates, or reads a system clock.
 */

export const INPUT_ACTIVITY_CONTRACT_VERSION = 1 as const;
export const DEFAULT_IDLE_AFTER_SECONDS = 5.0 as const;
export const DEFAULT_MAX_SOURCES = 16 as const;

export const INPUT_ACTIVITY_STATES = ["active", "idle", "unknown"] as const;
export type InputActivityState = (typeof INPUT_ACTIVITY_STATES)[number];

export const INPUT_ACTIVITY_PERMISSIONS = ["granted", "denied", "unavailable"] as const;
export type InputActivityPermission = (typeof INPUT_ACTIVITY_PERMISSIONS)[number];

export interface InputActivityObservation {
  source: string;
  permission: InputActivityPermission;
  keyboard_active: boolean;
  pointer_active: boolean;
  last_activity_at: number;
}

export interface InputActivityProbeConfig {
  idle_after_seconds: number;
  max_sources: number;
}

export interface InputActivitySnapshot {
  state: InputActivityState;
  keyboard_active: boolean;
  pointer_active: boolean;
  last_activity_at: number;
  idle_seconds: number;
  source: string;
  permission: InputActivityPermission;
}

export class InputActivityProbeError extends Error {
  /** Report a fail-closed aggregate-probe violation. */
  constructor(message: string) {
    super(message);
    this.name = "InputActivityProbeError";
  }
}

export const DEFAULT_INPUT_ACTIVITY_CONFIG: Readonly<InputActivityProbeConfig> = {
  idle_after_seconds: DEFAULT_IDLE_AFTER_SECONDS,
  max_sources: DEFAULT_MAX_SOURCES,
};

/** Validate the explicit aggregate-probe bounds. */
export function validateInputActivityConfig(config: InputActivityProbeConfig): void {
  if (!Number.isFinite(config.idle_after_seconds) || config.idle_after_seconds <= 0) {
    throw new InputActivityProbeError("idle_after_seconds must be finite and positive");
  }
  if (!Number.isInteger(config.max_sources) || config.max_sources <= 0) {
    throw new InputActivityProbeError("max_sources must be a positive integer");
  }
}

/** Validate one aggregate-only observation before it enters the reducer. */
export function validateInputActivityObservation(now: number, observation: InputActivityObservation): void {
  if (typeof observation !== "object" || observation === null || Array.isArray(observation)) {
    throw new InputActivityProbeError("invalid input activity observation: object required");
  }
  if (typeof observation.source !== "string") {
    throw new InputActivityProbeError("invalid input activity observation: source label");
  }
  if (observation.source.trim().length === 0 || /\s/.test(observation.source)) {
    throw new InputActivityProbeError(`invalid input activity observation ${observation.source}: source label`);
  }
  if (!INPUT_ACTIVITY_PERMISSIONS.includes(observation.permission)) {
    throw new InputActivityProbeError(`invalid input activity observation ${observation.source}: permission`);
  }
  if (typeof observation.keyboard_active !== "boolean" || typeof observation.pointer_active !== "boolean") {
    throw new InputActivityProbeError(
      `invalid input activity observation ${observation.source}: activity flags`,
    );
  }
  if (typeof observation.last_activity_at !== "number") {
    throw new InputActivityProbeError(
      `invalid input activity observation ${observation.source}: timestamp`,
    );
  }
  if (
    !Number.isFinite(observation.last_activity_at)
    || observation.last_activity_at < 0
    || observation.last_activity_at > now
  ) {
    throw new InputActivityProbeError(
      `invalid input activity observation ${observation.source}: timestamp`,
    );
  }
  if (
    observation.permission !== "granted"
    && (observation.keyboard_active || observation.pointer_active)
  ) {
    throw new InputActivityProbeError(
      `invalid input activity observation ${observation.source}: activity requires permission`,
    );
  }
  if (
    observation.permission === "granted"
    && (observation.keyboard_active || observation.pointer_active)
    && observation.last_activity_at === 0
  ) {
    throw new InputActivityProbeError(
      `invalid input activity observation ${observation.source}: active timestamp`,
    );
  }
}

/** Aggregate bounded host observations at an injected current time. */
export function aggregateInputActivity(
  now: number,
  observations: readonly InputActivityObservation[],
  config: InputActivityProbeConfig = DEFAULT_INPUT_ACTIVITY_CONFIG,
): InputActivitySnapshot {
  validateInputActivityConfig(config);
  if (!Number.isFinite(now) || now < 0) {
    throw new InputActivityProbeError("input activity now must be finite and non-negative");
  }
  if (observations.length > config.max_sources) {
    throw new InputActivityProbeError(`input activity source limit exceeded: ${config.max_sources}`);
  }

  const seen = new Set<string>();
  let granted = false;
  let denied = false;
  let keyboardActive = false;
  let pointerActive = false;
  let lastActivityAt = 0;
  for (const observation of observations) {
    validateInputActivityObservation(now, observation);
    if (seen.has(observation.source)) {
      throw new InputActivityProbeError(
        `invalid input activity observation ${observation.source}: duplicate source`,
      );
    }
    seen.add(observation.source);
    if (observation.permission === "granted") {
      granted = true;
      lastActivityAt = Math.max(lastActivityAt, observation.last_activity_at);
      const fresh = now - observation.last_activity_at <= config.idle_after_seconds;
      keyboardActive ||= fresh && observation.keyboard_active;
      pointerActive ||= fresh && observation.pointer_active;
    } else if (observation.permission === "denied") {
      denied = true;
    }
  }

  const state: InputActivityState = keyboardActive || pointerActive
    ? "active"
    : granted ? "idle" : "unknown";
  return {
    state,
    keyboard_active: keyboardActive,
    pointer_active: pointerActive,
    last_activity_at: lastActivityAt,
    idle_seconds: lastActivityAt > 0 ? Math.max(0, now - lastActivityAt) : 0,
    source: "rust-probe",
    permission: granted ? "granted" : denied ? "denied" : "unavailable",
  };
}

/** Validate a serialized snapshot without accepting raw input fields. */
export function validateInputActivitySnapshot(value: unknown): string[] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return ["input activity snapshot must be an object"];
  }
  const snapshot = value as Record<string, unknown>;
  const errors: string[] = [];
  if (!INPUT_ACTIVITY_STATES.includes(snapshot.state as InputActivityState)) errors.push("invalid state");
  if (typeof snapshot.keyboard_active !== "boolean") errors.push("keyboard_active must be boolean");
  if (typeof snapshot.pointer_active !== "boolean") errors.push("pointer_active must be boolean");
  if (typeof snapshot.source !== "string" || snapshot.source.length === 0) errors.push("source is required");
  if (!INPUT_ACTIVITY_PERMISSIONS.includes(snapshot.permission as InputActivityPermission)) {
    errors.push("invalid permission");
  }
  for (const field of ["last_activity_at", "idle_seconds"] as const) {
    if (typeof snapshot[field] !== "number" || !Number.isFinite(snapshot[field])) {
      errors.push(`${field} must be finite`);
    }
  }
  if (typeof snapshot.idle_seconds === "number" && snapshot.idle_seconds < 0) {
    errors.push("idle_seconds must be non-negative");
  }
  return errors;
}
