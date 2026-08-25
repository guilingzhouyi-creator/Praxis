//! Independent platform value and command-construction tests for the Rust kernel.

use l1_kernel_rs::platform::{GrepOptions, PlatformDescriptor, PlatformSnapshot};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct PlatformVector {
    snapshot: PlatformSnapshot,
    grep_options: GrepVector,
    grep_command: Vec<String>,
    url_parts: Vec<String>,
    url: String,
    temp_system: String,
    temp_dir: String,
    tcp_endpoint: String,
    tcp_default_host: String,
    tcp: (String, u16),
}

#[derive(Debug, Deserialize)]
struct GrepVector {
    pattern: String,
    path: String,
    fixed: bool,
    ignore_case: bool,
    max_count: usize,
    glob_pattern: String,
    file_type: String,
}

#[test]
fn posix_snapshot_matches_platform_and_rg_contract() {
    let descriptor = PlatformDescriptor::from_snapshot(PlatformSnapshot::posix(
        "/bin/bash",
        "/usr/bin/python",
        true,
    ))
    .expect("posix snapshot");
    assert!(descriptor.is_posix);
    assert_eq!(descriptor.selected_shell, "/bin/bash");
    assert_eq!(descriptor.temp_dir("/tmp"), "/tmp/praxis");
    assert_eq!(
        descriptor.join_url(["/api/", "/v2/", "/health"]),
        "api/v2/health"
    );
    assert_eq!(
        descriptor.grep_command(GrepOptions {
            pattern: "needle",
            path: ".",
            fixed: true,
            ignore_case: true,
            max_count: 3,
            glob_pattern: "*.rs",
            file_type: "rust",
            rg_available: true,
        }),
        [
            "rg",
            "-n",
            "--no-heading",
            "-F",
            "-i",
            "--max-count",
            "3",
            "--glob",
            "*.rs",
            "--type",
            "rust",
            "needle",
            "."
        ]
    );
}

#[test]
fn windows_platform_and_endpoint_are_provider_neutral() {
    let descriptor = PlatformDescriptor::from_snapshot(PlatformSnapshot::windows(
        "C:\\Windows\\System32\\cmd.exe",
        "C:\\Python\\python.exe",
        false,
    ))
    .expect("windows snapshot");
    assert_eq!(descriptor.shell_name, "cmd.exe");
    assert_eq!(descriptor.selected_shell, "C:\\Windows\\System32\\cmd.exe");
    assert_eq!(
        descriptor.grep_command(GrepOptions {
            pattern: "needle",
            path: "src",
            fixed: true,
            ignore_case: true,
            max_count: 0,
            glob_pattern: "*.py",
            file_type: "",
            rg_available: false,
        }),
        ["findstr", "/n", "/s", "/i", "/x", "/c:needle", "src\\*.py"]
    );
    assert_eq!(
        descriptor.parse_tcp_endpoint("127.0.0.1:42101", "localhost"),
        Ok(("127.0.0.1".to_owned(), 42101))
    );
    assert_eq!(
        descriptor.parse_tcp_endpoint(":42101", "localhost"),
        Ok(("localhost".to_owned(), 42101))
    );
}

#[test]
fn shared_platform_vectors_match_python_reference() {
    let vectors: Vec<PlatformVector> = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_platform_vectors.json"
    ))
    .expect("platform fixture must be valid JSON");
    for vector in vectors {
        let rg_available = vector.snapshot.rg_available;
        let descriptor = PlatformDescriptor::from_snapshot(vector.snapshot).expect("descriptor");
        assert_eq!(
            descriptor.grep_command(GrepOptions {
                pattern: &vector.grep_options.pattern,
                path: &vector.grep_options.path,
                fixed: vector.grep_options.fixed,
                ignore_case: vector.grep_options.ignore_case,
                max_count: vector.grep_options.max_count,
                glob_pattern: &vector.grep_options.glob_pattern,
                file_type: &vector.grep_options.file_type,
                rg_available,
            }),
            vector.grep_command
        );
        assert_eq!(
            descriptor.join_url(vector.url_parts.iter().map(String::as_str)),
            vector.url
        );
        assert_eq!(descriptor.temp_dir(&vector.temp_system), vector.temp_dir);
        assert_eq!(
            descriptor.parse_tcp_endpoint(&vector.tcp_endpoint, &vector.tcp_default_host),
            Ok(vector.tcp)
        );
    }
}
