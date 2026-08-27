//! Provider-neutral platform values and command construction for the L1 boundary.

use serde::{Deserialize, Serialize};

/// Explicit platform snapshot supplied by the host adapter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlatformSnapshot {
    /// Whether the host uses the Windows command shell and path rules.
    /// Windows-family snapshot flag.
    /// Windows-family view flag.
    pub is_windows: bool,
    /// Whether the host is macOS.
    /// macOS snapshot flag.
    /// macOS view flag.
    pub is_mac: bool,
    /// Shell executable selected by the host environment.
    /// Shell binary path observed on the host.
    /// Resolved shell binary path.
    pub shell_path: String,
    /// Python executable exposed to bounded command adapters.
    /// Python interpreter path observed on the host.
    /// Python interpreter used by tooling.
    pub python_exe: String,
    /// Whether `rg` is available for search command construction.
    /// Whether ripgrep was found on PATH.
    /// Whether to emit ripgrep vs grep argument shapes.
    pub rg_available: bool,
    /// Path separator used by the host adapter.
    #[serde(default = "default_path_separator")]
    /// PATH list separator for this platform.
    /// PATH list separator.
    pub path_separator: String,
}

impl PlatformSnapshot {
    /// Build a deterministic snapshot for a POSIX host.
    pub fn posix(
        shell_path: impl Into<String>,
        python_exe: impl Into<String>,
        rg_available: bool,
    ) -> Self {
        Self {
            is_windows: false,
            is_mac: false,
            shell_path: shell_path.into(),
            python_exe: python_exe.into(),
            rg_available,
            path_separator: "/".to_owned(),
        }
    }

    /// Build a deterministic snapshot for a Windows host.
    pub fn windows(
        shell_path: impl Into<String>,
        python_exe: impl Into<String>,
        rg_available: bool,
    ) -> Self {
        Self {
            is_windows: true,
            is_mac: false,
            shell_path: shell_path.into(),
            python_exe: python_exe.into(),
            rg_available,
            path_separator: "\\".to_owned(),
        }
    }
}

/// Derived platform constants mirrored from `l1.kernel.platform`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlatformDescriptor {
    /// Whether the host is Windows.
    pub is_windows: bool,
    /// Whether the host is macOS.
    pub is_mac: bool,
    /// Whether the host is Linux.
    /// Linux view flag.
    pub is_linux: bool,
    /// Whether the host uses the NT OS family.
    /// NT (Windows) shell semantics flag.
    pub is_nt: bool,
    /// Whether the host uses POSIX semantics.
    /// POSIX shell semantics flag.
    pub is_posix: bool,
    /// Selected shell executable.
    pub shell_path: String,
    /// Stable shell display name.
    /// Shell family name (bash/zsh/powershell…).
    pub shell_name: String,
    /// Prompt prefix used by the shell adapter.
    /// Prompt string convention for this shell.
    pub shell_prompt: String,
    /// Shell executable selected by the host snapshot.
    /// Shell actually selected for command construction.
    pub selected_shell: String,
    /// Platform-specific ping count flag.
    /// Reachability-probe parameter for this OS.
    pub ping_param: String,
    /// Host Python executable.
    pub python_exe: String,
    /// Explicit subprocess encoding policy.
    /// Default text encoding name.
    pub default_encoding: String,
    /// Whether IPC should use Unix sockets.
    /// Whether IPC prefers Unix domain sockets.
    pub ipc_use_unix_socket: bool,
    /// IPC transport name (`unix` or `tcp`).
    /// Selected IPC transport label.
    pub ipc_transport: String,
    /// Host path separator used for pure path helpers.
    pub path_separator: String,
}

impl PlatformDescriptor {
    /// Derive platform constants from an adapter-owned snapshot.
    ///
    /// # Errors
    ///
    /// ConflictingOsFlags when multiple OS flags are set; MissingShellPath
    /// when the shell path is empty; InvalidPathSeparator when the separator
    /// is neither `:` nor `;`.
    pub fn from_snapshot(snapshot: PlatformSnapshot) -> Result<Self, PlatformError> {
        if snapshot.is_windows && snapshot.is_mac {
            return Err(PlatformError::ConflictingOsFlags);
        }
        if snapshot.shell_path.is_empty() {
            return Err(PlatformError::MissingShellPath);
        }
        if snapshot.path_separator != "/" && snapshot.path_separator != "\\" {
            return Err(PlatformError::InvalidPathSeparator);
        }

        let is_linux = !snapshot.is_windows && !snapshot.is_mac;
        let shell_name = if snapshot.is_windows {
            if snapshot
                .shell_path
                .to_ascii_lowercase()
                .contains("powershell")
            {
                "powershell.exe"
            } else {
                "cmd.exe"
            }
        } else {
            "bash"
        };
        let shell_prompt = if snapshot.is_windows {
            if shell_name == "powershell.exe" {
                "PS > "
            } else {
                "C:\\> "
            }
        } else {
            "$ "
        };

        Ok(Self {
            is_windows: snapshot.is_windows,
            is_mac: snapshot.is_mac,
            is_linux,
            is_nt: snapshot.is_windows,
            is_posix: !snapshot.is_windows,
            shell_path: snapshot.shell_path.clone(),
            shell_name: shell_name.to_owned(),
            shell_prompt: shell_prompt.to_owned(),
            selected_shell: snapshot.shell_path,
            ping_param: if snapshot.is_windows { "-n" } else { "-c" }.to_owned(),
            python_exe: snapshot.python_exe,
            default_encoding: "utf-8".to_owned(),
            ipc_use_unix_socket: !snapshot.is_windows,
            ipc_transport: if snapshot.is_windows { "tcp" } else { "unix" }.to_owned(),
            path_separator: snapshot.path_separator,
        })
    }

    /// Build a grep-style command without probing or invoking the host.
    pub fn grep_command(&self, options: GrepOptions<'_>) -> Vec<String> {
        if options.rg_available {
            let mut command = vec!["rg".to_owned(), "-n".to_owned(), "--no-heading".to_owned()];
            if options.fixed {
                command.push("-F".to_owned());
            }
            if options.ignore_case {
                command.push("-i".to_owned());
            }
            if options.max_count > 0 {
                command.extend(["--max-count".to_owned(), options.max_count.to_string()]);
            }
            if !options.glob_pattern.is_empty() {
                command.extend(["--glob".to_owned(), options.glob_pattern.to_owned()]);
            }
            if !options.file_type.is_empty() {
                command.extend(["--type".to_owned(), options.file_type.to_owned()]);
            }
            command.extend([options.pattern.to_owned(), options.path.to_owned()]);
            return command;
        }

        if self.is_windows {
            let mut command = vec!["findstr".to_owned(), "/n".to_owned(), "/s".to_owned()];
            if options.ignore_case {
                command.push("/i".to_owned());
            }
            if options.fixed {
                command.push("/x".to_owned());
                command.push(format!("/c:{}", options.pattern));
            } else {
                command.push(options.pattern.to_owned());
            }
            if !options.glob_pattern.is_empty() {
                command.push(format!("{}\\{}", options.path, options.glob_pattern));
            } else if !options.path.is_empty() {
                command.push(format!("{}\\*", options.path));
            }
            return command;
        }

        let mut command = vec!["grep".to_owned(), "-rn".to_owned()];
        if options.ignore_case {
            command.push("-i".to_owned());
        }
        if options.fixed {
            command.push("-F".to_owned());
        }
        if options.max_count > 0 {
            command.extend(["-m".to_owned(), options.max_count.to_string()]);
        }
        command.extend([options.pattern.to_owned(), options.path.to_owned()]);
        command
    }

    /// Join URL components while preserving the Python helper's slash rules.
    pub fn join_url<'a, I>(&self, parts: I) -> String
    where
        I: IntoIterator<Item = &'a str>,
    {
        parts
            .into_iter()
            .map(|part| part.trim_matches('/'))
            .collect::<Vec<_>>()
            .join("/")
    }

    /// Construct the stable runtime temporary directory without creating it.
    pub fn temp_dir(&self, system_temp: &str) -> String {
        join_path(system_temp, "praxis", &self.path_separator)
    }

    /// Parse a Windows-style TCP endpoint used by the IPC adapter.
    ///
    /// # Errors
    ///
    /// InvalidTcpEndpoint when host/port cannot be split or parsed.
    pub fn parse_tcp_endpoint(
        &self,
        endpoint: &str,
        default_host: &str,
    ) -> Result<(String, u16), PlatformError> {
        let (host, port_text) = endpoint
            .rsplit_once(':')
            .ok_or(PlatformError::InvalidTcpEndpoint)?;
        if port_text.is_empty() {
            return Err(PlatformError::InvalidTcpEndpoint);
        }
        let port = port_text
            .parse::<u16>()
            .map_err(|_| PlatformError::InvalidTcpPort)?;
        Ok((
            if host.is_empty() {
                default_host.to_owned()
            } else {
                host.to_owned()
            },
            port,
        ))
    }
}

/// Options for a pure grep command description.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GrepOptions<'a> {
    /// Search pattern.
    /// Search pattern to pass through.
    pub pattern: &'a str,
    /// Search root.
    /// Target path or directory.
    pub path: &'a str,
    /// Request literal matching.
    /// Treat `pattern` as a literal string.
    pub fixed: bool,
    /// Request case-insensitive matching.
    /// Case-insensitive matching.
    pub ignore_case: bool,
    /// Maximum matches per file, or zero for the default.
    /// Per-file match cap (0 = unlimited).
    pub max_count: usize,
    /// Optional glob filter.
    /// File glob filter (empty = all files).
    pub glob_pattern: &'a str,
    /// Optional ripgrep file type.
    /// ripgrep file-type filter (empty = none).
    pub file_type: &'a str,
    /// Whether the host adapter found `rg`.
    pub rg_available: bool,
}

/// Errors raised while validating a platform snapshot or endpoint.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PlatformError {
    /// Windows and macOS were both asserted.
    ConflictingOsFlags,
    /// No shell executable was supplied.
    MissingShellPath,
    /// A separator other than `/` or `\\` was supplied.
    InvalidPathSeparator,
    /// Endpoint is not in `host:port` form.
    InvalidTcpEndpoint,
    /// Endpoint port is not an unsigned 16-bit integer.
    InvalidTcpPort,
}

fn default_path_separator() -> String {
    "/".to_owned()
}

fn join_path(root: &str, child: &str, separator: &str) -> String {
    if root.is_empty() {
        return child.to_owned();
    }
    format!(
        "{}{}{}",
        root.trim_end_matches(['/', '\\']),
        separator,
        child
    )
}
