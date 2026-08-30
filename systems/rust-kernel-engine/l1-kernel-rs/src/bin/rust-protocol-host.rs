//! Bounded stdio protocol host for the clean-break kernel.
//!
//! Mirrors the `python -m l2.protocol.host` I/O contract (rulings R5/R7):
//! one JSONL envelope per stdin line, response envelopes plus a trailing
//! ack per accepted input on stdout, and stderr reserved for transport-
//! level rejections. Frames over the 1 MiB cap are rejected on stderr
//! before parsing. Gate denials and routing violations travel as
//! `result{success:false}` envelopes; only undecodable frames fall back
//! to the synthetic `"-"` session, mirroring the Python host.

use std::collections::BTreeMap;
use std::io::{BufRead, BufWriter, Write};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use l1_kernel_rs::protocol::{Message, MessageKind, ProtocolError, encode_message};
use l1_kernel_rs::protocol_host::ProtocolHostError;
use l1_kernel_rs::protocol_host_runtime::ProtocolHostRuntime;

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}

/// Encode one outbound envelope, mapping protocol failures to I/O errors.
fn wire(message: &Message) -> std::io::Result<String> {
    encode_message(message)
        .map_err(|error| std::io::Error::new(std::io::ErrorKind::InvalidData, error.to_string()))
}

/// Synthetic failure envelope for frames that cannot reach the router
/// (undecodable JSON or contract-invalid). The Python host replies on the
/// synthetic `"-"` session for these; seq is a host-local counter.
fn synthetic_error(seq: u64, error: &str) -> Result<Message, ProtocolError> {
    let message = Message::new(
        "-",
        seq,
        MessageKind::Result,
        BTreeMap::from([
            ("success".to_owned(), serde_json::Value::Bool(false)),
            (
                "error".to_owned(),
                serde_json::Value::String(error.to_owned()),
            ),
        ]),
        "",
        now_seconds(),
    );
    Ok(message)
}

fn main() -> std::io::Result<()> {
    let host = ProtocolHostRuntime::default();
    let stdin = std::io::stdin();
    let mut stdout = BufWriter::new(std::io::stdout().lock());
    let synthetic_seq = AtomicU64::new(0);

    for line in stdin.lock().lines() {
        let line = line?;
        match host.route_line(&line) {
            Err(ProtocolHostError::FrameTooLarge {
                actual_bytes,
                max_bytes,
            }) => {
                eprintln!("protocol frame rejected: {actual_bytes} bytes exceeds {max_bytes}");
                continue;
            }
            Err(ProtocolHostError::Protocol(error)) => {
                let seq = synthetic_seq.fetch_add(1, Ordering::Relaxed) + 1;
                match synthetic_error(seq, &error.to_string()) {
                    Ok(envelope) => writeln!(stdout, "{}", wire(&envelope)?)?,
                    Err(encoding_error) => {
                        eprintln!("protocol error envelope failed: {encoding_error}")
                    }
                }
            }
            Ok(routed) => {
                for response in routed.responses {
                    writeln!(stdout, "{}", wire(&response)?)?;
                }
                writeln!(stdout, "{}", wire(&routed.ack)?)?;
            }
        }
        stdout.flush()?;
    }
    stdout.flush()
}
