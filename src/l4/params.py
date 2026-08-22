"""L4 domain constants (WS5.4) — API/eval/diff/security-gate business values.

Moved out of l1.kernel.params so the kernel namespace only carries mechanism
constants; the Rust rewrite boundary stays lean.
"""

from typing import Final

API_CORS_ALLOW_HEADERS: Final[str] = "Content-Type"
API_CORS_ALLOW_METHODS: Final[str] = "GET, POST, DELETE, OPTIONS"
API_CORS_ORIGIN: Final[str] = "*"
API_GATEWAY_HOST: Final[str] = "127.0.0.1"
API_GATEWAY_PORT: Final[int] = 8080
API_GATEWAY_QUEUE_TIMEOUT: Final[float] = 30.0
API_MAX_BODY_BYTES: Final[int] = 1_048_576
API_MIDDLEWARE_TIMEOUT: Final[float] = 30.0
API_PAGE_MAX_LIMIT: Final[int] = 100
API_WS_PORT: Final[int] = 8081
DIFF_CHAR_LEVEL_MAX_LINES: Final[int] = 10
DIFF_CONTEXT_LINES: Final[int] = 3
DIFF_DICTIONARY_FILE: Final[str] = "diff_dictionary.bin"
DIFF_LINE_SCORE_ADDED_WEIGHT: Final[float] = 1.0
DIFF_LINE_SCORE_MAX_PER_HUNK: Final[float] = 5.0
DIFF_LINE_SCORE_REMOVED_WEIGHT: Final[float] = 0.7
DIFF_LINE_SCORE_REVIEWED_WEIGHT: Final[float] = 1.3
DIFF_PERSIST_ENABLED_DEFAULT: Final[bool] = False
DIFF_PERSIST_FILE: Final[str] = "diff_persist.jsonl"
DIFF_PERSIST_FLUSH_INTERVAL: Final[float] = 5.0
DIFF_PERSIST_R4_FONDS: Final[str] = "diff"
DIFF_PERSIST_R4_SERIES: Final[str] = "stitched"
DIFF_PERSIST_RING_CAPACITY: Final[int] = 200
DIFF_PINGPONG_WINDOW_SECONDS: Final[float] = 30.0
EVAL_ALLOC_SHARD_WORKERS: Final[list[int]] = [1, 2, 4, 8]
EVAL_AMDAHL_AGENTS: Final[list[int]] = [1, 2, 4, 8]
EVAL_AMDAHL_LATENCY_PERCENTILES: Final[tuple[float, float]] = (0.50, 0.95)
EVAL_AMDAHL_RING_CAPACITY: Final[int] = 1
EVAL_AMDAHL_ROUNDS: Final[int] = 3
EVAL_AMDAHL_TASK_TIMEOUT: Final[float] = 30.0
EVAL_AMDAHL_TOTAL_WORK_ITEMS: Final[int] = 200_000
EVAL_CONSTITUTION_ITERS: Final[int] = 20_000
EVAL_DIFF_COMPRESS_ITERS: Final[int] = 5_000
EVAL_DIFF_HEADER_ITERS: Final[int] = 100_000
EVAL_DIFF_HUNK_ITERS: Final[int] = 5_000
EVAL_EVENT_BOUNDED_ITERS: Final[int] = 16
EVAL_EVENT_ITERS: Final[int] = 10_000
EVAL_EVENT_LISTENERS: Final[list[int]] = [0, 4, 16]
EVAL_GATECHAIN_ITERS: Final[int] = 20_000
EVAL_INTERRUPT_ITERS: Final[int] = 50_000
EVAL_IPC_ITERS: Final[int] = 50_000
EVAL_IPC_RTT_ITERS: Final[int] = 20_000
EVAL_JSON_PARSE_ITERS: Final[int] = 5_000
EVAL_JSON_PAYLOAD_BYTES: Final[int] = 64_000
EVAL_LOCKFREE_ITERS: Final[int] = 50_000
EVAL_LOCK_CONTEND_TOTAL_OPS: Final[int] = 160_000
EVAL_LOCK_CONTEND_WORKERS: Final[list[int]] = [1, 2, 4, 8]
EVAL_MEMORY_ALLOC_ITERS: Final[int] = 20_000
EVAL_PERSIST_ITERS: Final[int] = 5_000
EVAL_PRESSURE_AGENTS: Final[int] = 64
EVAL_PROCESS_ITERS: Final[int] = 20_000
EVAL_QUEUE_ITERS: Final[int] = 50_000
EVAL_RECLAIM_ITERS: Final[int] = 20_000
EVAL_REPUTATION_ITERS: Final[int] = 50_000
EVAL_RESOURCE_ITERS: Final[int] = 50_000
EVAL_SATURATION_DELTA: Final[float] = 0.1
EVAL_SCHED_LATENCY_TASKS: Final[int] = 2_000
EVAL_SERIAL_P_THRESHOLD: Final[float] = 0.5
EVAL_SKILL_ITERS: Final[int] = 5_000
EVAL_SWAP_ITERS: Final[int] = 5_000
EVAL_SYNC_ITERS: Final[int] = 50_000
EVAL_TERRITORY_ITERS: Final[int] = 100_000
EVAL_VFS_ITERS: Final[int] = 10_000
SECURITY_GATE_SCORE_AUTH: Final[float] = 0.5
SECURITY_GATE_SCORE_CLEARANCE: Final[float] = 0.1
SECURITY_GATE_SCORE_CONSTITUTION: Final[float] = 0.3
SECURITY_GATE_SCORE_CONSTITUTION_ERROR: Final[float] = 0.5
SECURITY_GATE_SCORE_GATECHAIN: Final[float] = 0.5
SECURITY_GATE_SCORE_RATE_LIMIT: Final[float] = 0.4
SECURITY_GATE_SCORE_TOOL_MODE: Final[float] = 0.8
