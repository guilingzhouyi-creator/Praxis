/**
 * Bounded limits for the TypeScript L3 governance projections.
 *
 * These values constrain coordination and audit memory only. Rust remains the
 * authority for capability, process, terminal, and hard-policy decisions.
 */

/** Maximum number of sensitive matches returned by one scan. */
export const L3_GOVERNANCE_MAX_SENSITIVE_HITS = 16;
/** Maximum characters retained for one sensitive-match fragment. */
export const L3_GOVERNANCE_MAX_SENSITIVE_FRAGMENT = 24;
/** Maximum serialized raw snapshot bytes retained by one evidence point. */
export const L3_GOVERNANCE_MAX_EVIDENCE_RAW_BYTES = 2_048;
/** Maximum evidence points retained by the in-memory ledger. */
export const L3_GOVERNANCE_MAX_EVIDENCE_POINTS = 512;
/** Maximum chains retained by the in-memory ledger. */
export const L3_GOVERNANCE_MAX_EVIDENCE_CHAINS = 64;
/** Maximum UTF-8 bytes retained for evidence phase, target, and source fields. */
export const L3_GOVERNANCE_MAX_EVIDENCE_LABEL_BYTES = 256;
/** Maximum suggestions retained for one review response. */
export const L3_GOVERNANCE_MAX_REVIEW_SUGGESTIONS = 16;
/** Maximum characters retained for one review reason or suggestion. */
export const L3_GOVERNANCE_MAX_REVIEW_TEXT = 500;
/** Default maximum review correction rounds before escalation. */
export const L3_GOVERNANCE_DEFAULT_REVIEW_MAX_ROUNDS = 2;
/** Default recursive-compression threshold; zero disables the threshold. */
export const L3_GOVERNANCE_DEFAULT_COMPRESSION_THRESHOLD = 0;
/** Default state of the compression circuit breaker. */
export const L3_GOVERNANCE_DEFAULT_COMPRESSION_BREAKER_ENABLED = true;
/** Compression failures in this window trip the default breaker. */
export const L3_GOVERNANCE_DEFAULT_COMPRESSION_ERROR_STORM_THRESHOLD = 5;
/** Error-storm window in seconds. */
export const L3_GOVERNANCE_DEFAULT_COMPRESSION_ERROR_STORM_WINDOW_SECONDS = 60;
/** Maximum paths tracked by one verify-cadence projection. */
export const L3_GOVERNANCE_MAX_VERIFY_PATHS = 256;
/** Maximum verification evidence entries retained by one cadence projection. */
export const L3_GOVERNANCE_MAX_VERIFY_EVIDENCE = 256;
/** Maximum characters retained for one verification command/evidence string. */
export const L3_GOVERNANCE_MAX_VERIFY_TEXT = 500;
/** Prefix length used for evidence chain and point identifiers. */
export const L3_GOVERNANCE_HASH_PREFIX_LENGTH = 16;
