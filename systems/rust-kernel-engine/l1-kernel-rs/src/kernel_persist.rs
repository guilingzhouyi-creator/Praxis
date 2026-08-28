//! Rust candidate for the append-only kernel event journal.

use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, PoisonError};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

/// Default number of appends between durable flushes.
pub const PERSIST_COMMIT_BATCH: usize = 32;
/// Default result page size for journal queries.
pub const PERSIST_QUERY_LIMIT: usize = 100;

/// One immutable journal row shared across language boundaries.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EventRecord {
    /// Monotonic event sequence number.
    pub seq: u64,
    /// Event type or operation name.
    pub event: String,
    /// JSON payload associated with the event.
    pub payload: Value,
    /// Wall-clock event timestamp in Unix seconds.
    pub ts: f64,
}

impl EventRecord {
    /// Build one journal event record with its sequence number.
    fn new(seq: u64, event: impl Into<String>, payload: Value) -> Self {
        Self {
            seq,
            event: event.into(),
            payload,
            ts: unix_timestamp(),
        }
    }
}

struct JournalState {
    file: File,
    records: Vec<EventRecord>,
    next_seq: u64,
    pending: usize,
}

/// Thread-safe append-only JSONL event journal.
pub struct EventStore {
    path: PathBuf,
    commit_batch: usize,
    state: Mutex<JournalState>,
}

impl EventStore {
    /// Open or create a journal using the default commit batch.
    pub fn open(path: impl AsRef<Path>) -> io::Result<Self> {
        Self::with_commit_batch(path, PERSIST_COMMIT_BATCH)
    }

    /// Open or create a journal with an explicit flush batch.
    pub fn with_commit_batch(path: impl AsRef<Path>, commit_batch: usize) -> io::Result<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent()
            && !parent.as_os_str().is_empty()
        {
            std::fs::create_dir_all(parent)?;
        }
        let read_file = OpenOptions::new()
            .read(true)
            .append(true)
            .create(true)
            .open(&path)?;
        let records = load_records(&read_file)?;
        let next_seq = records
            .last()
            .map_or(1, |record| record.seq.saturating_add(1));
        Ok(Self {
            path,
            commit_batch: commit_batch.max(1),
            state: Mutex::new(JournalState {
                file: read_file,
                records,
                next_seq,
                pending: 0,
            }),
        })
    }

    /// Return the path backing this journal.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Append one event and return its assigned sequence number.
    pub fn append(&self, event: impl Into<String>, payload: Option<Value>) -> io::Result<u64> {
        let mut state = self.lock_state();
        let record = EventRecord::new(state.next_seq, event, payload.unwrap_or_else(empty_object));
        write_record(&mut state.file, &record)?;
        let seq = record.seq;
        state.records.push(record);
        state.next_seq = state.next_seq.saturating_add(1);
        state.pending += 1;
        if state.pending >= self.commit_batch {
            flush_locked(&mut state)?;
        }
        Ok(seq)
    }

    /// Append multiple events under one journal lock and perform one durable flush.
    pub fn append_many<I, E>(&self, events: I) -> io::Result<Vec<u64>>
    where
        I: IntoIterator<Item = (E, Value)>,
        E: Into<String>,
    {
        let mut state = self.lock_state();
        let mut records = Vec::new();
        let mut next_seq = state.next_seq;
        for (event, payload) in events {
            records.push(EventRecord::new(next_seq, event, payload));
            next_seq = next_seq.saturating_add(1);
        }
        let sequences = records.iter().map(|record| record.seq).collect::<Vec<_>>();
        for record in &records {
            write_record(&mut state.file, record)?;
        }
        state.records.extend(records);
        state.next_seq = next_seq;
        state.pending = 0;
        flush_locked(&mut state)?;
        Ok(sequences)
    }

    /// Flush buffered bytes and make the journal durable.
    pub fn flush(&self) -> io::Result<()> {
        let mut state = self.lock_state();
        flush_locked(&mut state)
    }

    /// Query records after a sequence, optionally filtering by event type.
    pub fn query(
        &self,
        event_type: Option<&str>,
        after_seq: u64,
        limit: usize,
    ) -> io::Result<Vec<EventRecord>> {
        self.flush()?;
        let state = self.lock_state();
        Ok(state
            .records
            .iter()
            .filter(|record| record.seq > after_seq)
            .filter(|record| event_type.is_none_or(|kind| record.event == kind))
            .take(limit)
            .cloned()
            .collect())
    }

    /// Count records, optionally restricted to one event type.
    pub fn count(&self, event_type: Option<&str>) -> io::Result<usize> {
        self.flush()?;
        let state = self.lock_state();
        Ok(state
            .records
            .iter()
            .filter(|record| event_type.is_none_or(|kind| record.event == kind))
            .count())
    }

    /// Return the highest assigned sequence number, or zero when empty.
    pub fn last_seq(&self) -> io::Result<u64> {
        self.flush()?;
        let state = self.lock_state();
        Ok(state.records.last().map_or(0, |record| record.seq))
    }

    fn lock_state(&self) -> MutexGuard<'_, JournalState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Replay all journal records from an opened file.
fn load_records(file: &File) -> io::Result<Vec<EventRecord>> {
    let reader = BufReader::new(file.try_clone()?);
    let mut records = Vec::new();
    let mut expected_seq = 1;
    for (line_number, line) in reader.lines().enumerate() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let record: EventRecord = serde_json::from_str(&line).map_err(|error| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                format!("invalid event journal row {}: {error}", line_number + 1),
            )
        })?;
        if record.seq != expected_seq {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!(
                    "event journal sequence gap at row {}: expected {}, got {}",
                    line_number + 1,
                    expected_seq,
                    record.seq
                ),
            ));
        }
        expected_seq = expected_seq.saturating_add(1);
        records.push(record);
    }
    Ok(records)
}

/// Append one record to the journal file.
fn write_record(file: &mut File, record: &EventRecord) -> io::Result<()> {
    serde_json::to_writer(&mut *file, record)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    file.write_all(b"\n")
}

/// Flush the journal file under the already-held state lock.
fn flush_locked(state: &mut JournalState) -> io::Result<()> {
    state.file.flush()?;
    state.file.sync_data()?;
    state.pending = 0;
    Ok(())
}

fn empty_object() -> Value {
    json!({})
}

fn unix_timestamp() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}
