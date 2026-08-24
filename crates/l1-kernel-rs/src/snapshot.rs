//! Bounded deterministic snapshot pages for Rust-owned registry books.
//!
//! The helpers in this module retain only `limit + 1` registry handles in a
//! bounded max-heap while selecting from ordered or hash-backed books. They
//! deliberately do not promise a consistent multi-page view while writers are
//! active; durable checkpoint callers keep using each book's complete
//! deterministic snapshot API.

use std::collections::BinaryHeap;
use std::fmt;

use serde::{Deserialize, Serialize};

/// Maximum number of snapshots returned by one public book page.
pub const BOOK_SNAPSHOT_MAX_PAGE_SIZE: usize = 512;

/// Stable bounded page returned by a registry book.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BookSnapshotPage<T> {
    /// Snapshots in ascending logical identity order.
    pub items: Vec<T>,
    /// Exclusive identity cursor for the next page when more records existed.
    pub next_cursor: Option<String>,
}

/// Fail-closed errors for a public book snapshot page request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BookSnapshotPageError {
    /// The requested page size was zero or exceeded the public bound.
    InvalidLimit { limit: usize, max: usize },
}

impl fmt::Display for BookSnapshotPageError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidLimit { limit, max } => {
                write!(
                    formatter,
                    "snapshot page limit {limit} is outside 1..={max}"
                )
            }
        }
    }
}

impl std::error::Error for BookSnapshotPageError {}

/// One candidate retained by the bounded page selector.
struct SnapshotCandidate<T> {
    identity: String,
    value: T,
}

impl<T> PartialEq for SnapshotCandidate<T> {
    fn eq(&self, other: &Self) -> bool {
        self.identity == other.identity
    }
}

impl<T> Eq for SnapshotCandidate<T> {}

impl<T> PartialOrd for SnapshotCandidate<T> {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl<T> Ord for SnapshotCandidate<T> {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.identity.cmp(&other.identity)
    }
}

/// Bounded max-heap retained while selecting one page.
pub(crate) struct BookSnapshotPageCandidates<T> {
    heap: BinaryHeap<SnapshotCandidate<T>>,
}

/// Validate and execute one bounded snapshot page selection.
pub(crate) struct BookSnapshotPageRequest<'a> {
    after: Option<&'a str>,
    limit: usize,
}

impl<'a> BookSnapshotPageRequest<'a> {
    /// Create one page request with an optional exclusive identity cursor.
    pub(crate) fn new(after: Option<&'a str>, limit: usize) -> Result<Self, BookSnapshotPageError> {
        if limit == 0 || limit > BOOK_SNAPSHOT_MAX_PAGE_SIZE {
            return Err(BookSnapshotPageError::InvalidLimit {
                limit,
                max: BOOK_SNAPSHOT_MAX_PAGE_SIZE,
            });
        }
        Ok(Self { after, limit })
    }

    /// Allocate the bounded candidate selector for this request.
    pub(crate) fn candidates<T>(&self) -> BookSnapshotPageCandidates<T> {
        BookSnapshotPageCandidates {
            heap: BinaryHeap::with_capacity(self.limit + 1),
        }
    }

    /// Return whether an identity is eligible after the exclusive cursor.
    pub(crate) fn is_after_cursor(&self, identity: &str) -> bool {
        self.after.is_none_or(|cursor| identity > cursor)
    }

    /// Return the maximum number of ordered identities needed from one source.
    pub(crate) const fn candidate_capacity(&self) -> usize {
        self.limit + 1
    }

    /// Retain one record only when it can belong to this page.
    pub(crate) fn retain_candidate<T>(
        &self,
        candidates: &mut BookSnapshotPageCandidates<T>,
        identity: &str,
        value: impl FnOnce() -> T,
    ) {
        if !self.is_after_cursor(identity) {
            return;
        }
        let capacity = self.candidate_capacity();
        if candidates.heap.len() == capacity
            && candidates
                .heap
                .peek()
                .is_some_and(|largest| identity >= largest.identity.as_str())
        {
            return;
        }
        candidates.heap.push(SnapshotCandidate {
            identity: identity.to_owned(),
            value: value(),
        });
        if candidates.heap.len() > capacity {
            let _ = candidates.heap.pop();
        }
    }

    /// Convert retained ordered handles into the public page response.
    pub(crate) fn finish<T>(
        self,
        candidates: BookSnapshotPageCandidates<T>,
    ) -> BookSnapshotPage<T> {
        let mut candidates = candidates.heap.into_vec();
        candidates.sort_unstable_by(|left, right| left.identity.cmp(&right.identity));
        let has_more = candidates.len() > self.limit;
        if has_more {
            let _ = candidates.pop();
        }
        let next_cursor = has_more.then(|| {
            candidates
                .last()
                .map(|candidate| candidate.identity.clone())
                .expect("a non-empty page has an exclusive cursor")
        });
        BookSnapshotPage {
            items: candidates
                .into_iter()
                .map(|candidate| candidate.value)
                .collect(),
            next_cursor,
        }
    }
}

impl<T> BookSnapshotPage<T> {
    /// Transform page items without changing cursor semantics.
    pub(crate) fn map_items<U>(self, map: impl FnMut(T) -> U) -> BookSnapshotPage<U> {
        BookSnapshotPage {
            items: self.items.into_iter().map(map).collect(),
            next_cursor: self.next_cursor,
        }
    }
}
