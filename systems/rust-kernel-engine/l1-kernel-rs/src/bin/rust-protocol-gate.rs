//! Canonicalize valid protocol-v1 JSONL frames without runtime dispatch.

use std::io::{self, BufRead, Write};

use l1_kernel_rs::protocol_host::ProtocolHost;

fn main() -> io::Result<()> {
    let host = ProtocolHost::default();
    let stdin = io::stdin();
    let mut stdout = io::BufWriter::new(io::stdout().lock());
    for (line_number, line) in stdin.lock().lines().enumerate() {
        let line = line?;
        match host.canonicalize_line(&line) {
            Ok(canonical) => writeln!(stdout, "{canonical}")?,
            Err(error) => {
                eprintln!("protocol line {} rejected: {error}", line_number + 1);
            }
        }
    }
    stdout.flush()
}
