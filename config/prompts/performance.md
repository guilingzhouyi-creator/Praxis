# Performance shared prompt

Under load, prefer efficient execution: reuse cached programs and results,
fold oversized tool outputs, and keep the context trail lean. Use the
compression-ratio baseline and the digest/offload caches to minimize token
pressure. Avoid redundant work — maintain stable prefixes for vendor KV
caches and batch where possible.
