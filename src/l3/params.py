"""L3 domain constants (WS5.4) — agent/card-gate/review/scout business values.

Moved out of l1.kernel.params so the kernel namespace only carries mechanism
constants; the Rust rewrite boundary stays lean.
"""

from typing import Final

CARD_GATE_APPROVAL_TIMEOUT: Final[float] = 3600.0
CARD_GATE_ARCH_KEYWORDS: Final[list[str]] = [
    "architecture",
    "redesign",
    "refactor",
    "migration",
    "restructure",
    "reorganize",
    "extract",
    "split",
    "merge module",
    "架构",
    "重构",
    "重设计",
    "迁移",
    "拆分",
]
CARD_GATE_AUTO_SAVE: Final[float] = 10.0
CARD_GATE_CONVENTION_TIMEOUT: Final[float] = 7200.0
CARD_GATE_HISTORY_LIMIT: Final[int] = 50
CARD_GATE_MEDIUM_MAX_FILES: Final[int] = 5
CARD_GATE_MEDIUM_MAX_LINES: Final[int] = 200
CARD_GATE_SMALL_MAX_FILES: Final[int] = 1
CARD_GATE_SMALL_MAX_LINES: Final[int] = 50
REVIEW_AUTOFIX_ENABLED_DEFAULT: Final[bool] = True
REVIEW_MAX_ROUNDS: Final[int] = 2
REVIEW_PIPELINE_ENABLED_DEFAULT: Final[bool] = True
REVIEW_SMALL_CHANGE_MAX_LINES: Final[int] = 50
SCOUT_AGENT_NAME: Final[str] = "scout"
SCOUT_CACHE_MAX_ENTRIES: Final[int] = 200
SCOUT_CACHE_TTL: Final[float] = 30.0
SCOUT_COLLECT_TIMEOUT: Final[float] = 310.0
SCOUT_DIR_LIMIT: Final[int] = 100
SCOUT_FILE_READ_TRUNC: Final[int] = 4000
SCOUT_FINDINGS_DISPLAY_LIMIT: Final[int] = 5
SCOUT_FINDING_TRUNC: Final[int] = 500
SCOUT_GREP_MAX: Final[int] = 20
SCOUT_GREP_OUTPUT_TRUNC: Final[int] = 4000
SCOUT_LOOP_STEPS: Final[int] = 10
SCOUT_LOOP_TIMEOUT: Final[float] = 180.0
SCOUT_MONITOR_INTERVAL: Final[float] = 5.0
SCOUT_POOL_IDLE_TIMEOUT: Final[float] = 60.0
SCOUT_POOL_MAX: Final[int] = 16
SCOUT_POOL_MAX_PER_AGENT: Final[int] = 4
SCOUT_POOL_MAX_TOTAL: Final[int] = 16
SCOUT_POOL_MIN_IDLE: Final[int] = 2
SCOUT_PREFIX: Final[str] = "scout-"
SCOUT_RECALL_LIMIT: Final[int] = 200
SCOUT_RESULT_TRUNC: Final[int] = 300
SCOUT_RING_LIMIT: Final[str] = "RING_1"
SCOUT_TIMEOUT: Final[float] = 300.0
