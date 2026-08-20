//! Provider-neutral deployment path derivation for the L1 boundary.

use std::sync::{Mutex, MutexGuard, PoisonError};

use serde::{Deserialize, Serialize};

/// Deployment mode controlling default path layout.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum DeployMode {
    /// Local source checkout.
    #[serde(rename = "cli")]
    CliProject,
    /// Installed Python package.
    #[serde(rename = "pip")]
    PipPackage,
    /// IDE plugin install.
    #[serde(rename = "ide")]
    IdePlugin,
    /// macOS desktop bundle.
    #[serde(rename = "desktop_mac")]
    DesktopMac,
    /// Windows desktop bundle.
    #[serde(rename = "desktop_win")]
    DesktopWin,
    /// Container deployment.
    #[serde(rename = "docker")]
    Docker,
    /// Frozen binary deployment.
    #[serde(rename = "binary")]
    Binary,
}

impl DeployMode {
    /// Parse a configured deployment mode, falling back to source checkout for unknown values.
    pub fn parse(value: &str) -> Self {
        match value.to_ascii_lowercase().as_str() {
            "pip" => Self::PipPackage,
            "ide" => Self::IdePlugin,
            "desktop_mac" => Self::DesktopMac,
            "desktop_win" => Self::DesktopWin,
            "docker" => Self::Docker,
            "binary" => Self::Binary,
            _ => Self::CliProject,
        }
    }

    /// Return the stable Python wire value.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::CliProject => "cli",
            Self::PipPackage => "pip",
            Self::IdePlugin => "ide",
            Self::DesktopMac => "desktop_mac",
            Self::DesktopWin => "desktop_win",
            Self::Docker => "docker",
            Self::Binary => "binary",
        }
    }
}

/// Inputs supplied by deployment/environment adapters.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PathInputs {
    /// Selected deployment mode.
    pub deploy_mode: DeployMode,
    /// User home directory.
    pub home_dir: String,
    /// Windows roaming application-data directory.
    #[serde(default)]
    pub appdata_dir: String,
    /// Windows local application-data directory.
    #[serde(default)]
    pub localappdata_dir: String,
    /// Installation prefix for installed data files.
    #[serde(default)]
    pub prefix_dir: String,
    /// Source or package root used for read-only project assets.
    #[serde(default)]
    pub package_root: String,
    /// Frozen executable directory.
    #[serde(default)]
    pub executable_dir: String,
    /// Host temporary directory.
    pub temp_dir: String,
    /// Host OS path separator.
    pub path_separator: String,
    /// Whether the host is Windows.
    pub is_windows: bool,
    /// Whether the host is macOS.
    pub is_mac: bool,
    /// Optional deployment data root override.
    #[serde(default)]
    pub data_dir_override: String,
    /// Optional config directory override.
    #[serde(default)]
    pub config_dir_override: String,
    /// Optional config file override.
    #[serde(default)]
    pub config_file_override: String,
    /// Optional install directory override.
    #[serde(default)]
    pub install_dir_override: String,
    /// Optional config-template directory override.
    #[serde(default)]
    pub templates_dir_override: String,
    /// Optional isolated skill root override.
    #[serde(default)]
    pub skill_dir_override: String,
    /// Skill write scope (`project` or `global`).
    #[serde(default = "default_skill_scope")]
    pub skill_scope: String,
}

impl PathInputs {
    /// Create inputs for a deterministic POSIX source checkout.
    pub fn cli(
        home_dir: impl Into<String>,
        package_root: impl Into<String>,
        temp_dir: impl Into<String>,
    ) -> Self {
        Self {
            deploy_mode: DeployMode::CliProject,
            home_dir: home_dir.into(),
            appdata_dir: String::new(),
            localappdata_dir: String::new(),
            prefix_dir: String::new(),
            package_root: package_root.into(),
            executable_dir: String::new(),
            temp_dir: temp_dir.into(),
            path_separator: "/".to_owned(),
            is_windows: false,
            is_mac: false,
            data_dir_override: String::new(),
            config_dir_override: String::new(),
            config_file_override: String::new(),
            install_dir_override: String::new(),
            templates_dir_override: String::new(),
            skill_dir_override: String::new(),
            skill_scope: default_skill_scope(),
        }
    }

    fn separator(&self) -> &str {
        if self.path_separator.is_empty() {
            if self.is_windows { "\\" } else { "/" }
        } else {
            &self.path_separator
        }
    }
}

/// Flattened runtime path set mirroring the Python `PraxisPaths` fields.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PraxisPaths {
    /// Selected deployment mode.
    pub deploy_mode: DeployMode,
    /// Runtime data root.
    pub data_dir: String,
    /// Runtime config directory.
    pub config_dir: String,
    /// Read-only installation root.
    pub install_dir: String,
    /// Shipped config-template source.
    pub config_templates_dir: String,
    /// Log directory.
    pub logs_dir: String,
    /// Runtime directories created by the boot layout step.
    pub layout_dirs: Vec<String>,
    /// Main config file.
    pub config_file: String,
    /// Constitution file name.
    pub constitution_file: String,
    /// Settings file name.
    pub settings_file: String,
    /// Skill discovery roots, in priority order.
    pub skill_dirs: Vec<String>,
    /// Global evolved skill target.
    pub skill_evolved_dir: String,
    /// Lean skill target.
    pub skill_lean_dir: String,
    /// Project evolved skill target.
    pub skill_project_evolved_dir: String,
    /// Skill write scope.
    pub skill_scope: String,
    /// Memory persistence root.
    pub memories_dir: String,
    /// Append-only event journal path.
    pub events_db: String,
    /// General state file.
    pub state_json: String,
    /// Card registry path.
    pub card_registry: String,
    /// Card gate path.
    pub card_gate: String,
    /// Pending card queue path.
    pub pending_queue: String,
    /// Issue table path.
    pub issue_table: String,
    /// Approval gate path.
    pub approval_gate: String,
    /// Capability gate path.
    pub capability_gate: String,
    /// Mute state path.
    pub mute_state: String,
    /// Runtime mode state path.
    pub mode_state: String,
    /// Todo state path.
    pub todo_state: String,
    /// Sandbox state path.
    pub sandbox_state: String,
    /// Todo table path.
    pub todo_table: String,
    /// Todo directory.
    pub todo_dir: String,
    /// Sandbox root.
    pub sandbox_root: String,
    /// IPC socket directory.
    pub socket_dir: String,
    /// Per-cell state template.
    pub cell_state_template: String,
    /// Monitor record template.
    pub seq_monitor_template: String,
    /// Monitor bus journal path.
    pub monitor_bus_log: String,
    /// VFS temporary directory.
    pub vfs_temp_path: String,
    /// Diff persistence path.
    pub diff_persist_file: String,
    /// Diff dictionary path.
    pub diff_dictionary_file: String,
    /// MCP state path.
    pub mcp_state: String,
    /// Transaction area path.
    pub transaction_area: String,
    /// Statechart path.
    pub statecharts: String,
    /// Execution result path.
    pub execution_results: String,
    /// Dialogue session path.
    pub dialogue_session: String,
    /// Message gate path.
    pub message_gate_state: String,
    /// Vault salt path.
    pub vault_salt: String,
    /// Chain key path.
    pub chain_key: String,
    /// Archive database path.
    pub archive_db: String,
    /// Ring-2 memory persistence filename template.
    pub memory_persist_ring2: String,
    /// Ring-3 memory persistence filename template.
    pub memory_persist_ring3: String,
    /// Per-cell sandbox state filename template.
    pub sandbox_state_template: String,
    /// Snapshot filename template.
    pub snapshot_path_template: String,
    /// Lean-case skill filename template.
    pub skill_lean_case_template: String,
    /// Agent session filename template.
    pub agent_session_template: String,
}

impl PraxisPaths {
    /// Return a JSON-compatible snapshot for a diagnostics or adapter boundary.
    pub fn to_json(&self) -> serde_json::Value {
        serde_json::to_value(self).expect("PraxisPaths is serializable")
    }
}

/// Derive all path values without reading environment variables or touching disk.
pub fn resolve_paths(input: &PathInputs) -> PraxisPaths {
    let separator = input.separator();
    let user_data_dir = if input.is_windows {
        join(
            fallback(&input.appdata_dir, &input.home_dir),
            "praxis",
            separator,
        )
    } else if input.is_mac {
        join(
            &join(&input.home_dir, "Library", separator),
            "Application Support/praxis",
            separator,
        )
    } else {
        join(
            &join(&input.home_dir, ".local", separator),
            "share/praxis",
            separator,
        )
    };
    let data_dir = if !input.data_dir_override.is_empty() {
        input.data_dir_override.clone()
    } else {
        match input.deploy_mode {
            DeployMode::CliProject => ".praxis".to_owned(),
            DeployMode::Docker => "/var/praxis".to_owned(),
            DeployMode::DesktopMac => join(
                &input.home_dir,
                "Library/Application Support/praxis",
                separator,
            ),
            DeployMode::DesktopWin => join(
                fallback(&input.appdata_dir, &input.home_dir),
                "praxis",
                separator,
            ),
            _ => user_data_dir,
        }
    };
    let config_dir = if !input.config_dir_override.is_empty() {
        input.config_dir_override.clone()
    } else if input.deploy_mode == DeployMode::CliProject {
        ".config/praxis".to_owned()
    } else {
        data_dir.clone()
    };
    let install_dir = if !input.install_dir_override.is_empty() {
        input.install_dir_override.clone()
    } else if input.deploy_mode == DeployMode::Docker {
        "/app".to_owned()
    } else if input.is_windows
        && matches!(
            input.deploy_mode,
            DeployMode::DesktopWin | DeployMode::Binary
        )
    {
        join(
            fallback(&input.localappdata_dir, &input.home_dir),
            "Programs/praxis",
            separator,
        )
    } else if input.is_mac
        && matches!(
            input.deploy_mode,
            DeployMode::DesktopMac | DeployMode::Binary
        )
    {
        "/Applications/Praxis.app".to_owned()
    } else {
        join(&input.home_dir, ".local/lib/praxis", separator)
    };
    let templates_dir = if !input.templates_dir_override.is_empty() {
        input.templates_dir_override.clone()
    } else if input.deploy_mode == DeployMode::CliProject {
        join(&input.package_root, "config", separator)
    } else {
        join(&input.prefix_dir, "share/praxis/config", separator)
    };
    let config_file = if !input.config_file_override.is_empty() {
        input.config_file_override.clone()
    } else if input.deploy_mode == DeployMode::CliProject {
        "config/praxis.yaml".to_owned()
    } else {
        join(&config_dir, "praxis.yaml", separator)
    };
    let skill_dirs = skill_dirs(input, &data_dir, separator);
    let skill_evolved_dir = join(&join(&data_dir, "skills", separator), "evolved", separator);
    let skill_lean_dir = join(&join(&data_dir, "skills", separator), "lean", separator);
    let skill_project_evolved_dir = if input.deploy_mode == DeployMode::CliProject {
        join(&input.package_root, "skills/evolved", separator)
    } else {
        skill_evolved_dir.clone()
    };
    let logs_dir = join(&data_dir, "logs", separator);
    let memories_dir = join(&data_dir, "memories", separator);
    let sandbox_root = join(&data_dir, "sandbox", separator);
    let socket_dir = join(&data_dir, "sockets", separator);
    let todo_dir = join(&data_dir, "todos", separator);
    let layout_dirs = vec![
        data_dir.clone(),
        join(&data_dir, "skills", separator),
        skill_evolved_dir.clone(),
        skill_lean_dir.clone(),
        memories_dir.clone(),
        sandbox_root.clone(),
        socket_dir.clone(),
        todo_dir.clone(),
        join(&data_dir, "l3a-outputs", separator),
        join(&data_dir, "cache", separator),
        logs_dir.clone(),
        config_dir.clone(),
    ];
    let child = |name: &str| join(&data_dir, name, separator);

    PraxisPaths {
        deploy_mode: input.deploy_mode,
        data_dir: data_dir.clone(),
        config_dir,
        install_dir,
        config_templates_dir: templates_dir,
        logs_dir: logs_dir.clone(),
        layout_dirs,
        config_file,
        constitution_file: ".praxis-rules.md".to_owned(),
        settings_file: ".praxis_settings.json".to_owned(),
        skill_dirs,
        skill_evolved_dir,
        skill_lean_dir,
        skill_project_evolved_dir,
        skill_scope: if input.skill_scope.is_empty() {
            default_skill_scope()
        } else {
            input.skill_scope.clone()
        },
        memories_dir,
        events_db: child("events.db"),
        state_json: child("state.json"),
        card_registry: child("card_registry.json"),
        card_gate: child("card_gate.json"),
        pending_queue: child("pending_queue.json"),
        issue_table: child("issue_table.json"),
        approval_gate: child("approval_gate.json"),
        capability_gate: child("capability_gate.json"),
        mute_state: child("mute_state.json"),
        mode_state: child("mode.json"),
        todo_state: child("todo_state.json"),
        sandbox_state: child("sandbox_state.json"),
        todo_table: child("todo_table.json"),
        todo_dir,
        sandbox_root,
        socket_dir,
        cell_state_template: child("cell_{}.json"),
        seq_monitor_template: child("seq_monitor_{}.json"),
        monitor_bus_log: child("monitor_bus.jsonl"),
        vfs_temp_path: input.temp_dir.clone(),
        diff_persist_file: child("diff_persist.jsonl"),
        diff_dictionary_file: child("diff_dictionary.bin"),
        mcp_state: child("mcp_state.json"),
        transaction_area: child("transaction_area.json"),
        statecharts: child("statecharts.json"),
        execution_results: child("execution_results.json"),
        dialogue_session: child("dialogue_session.json"),
        message_gate_state: child("message_gate.json"),
        vault_salt: child(".praxis_vault_salt"),
        chain_key: child(".chain_key"),
        archive_db: child("archive.db"),
        memory_persist_ring2: "memory_ring2.jsonl".to_owned(),
        memory_persist_ring3: "memory_ring3.db".to_owned(),
        sandbox_state_template: "{cell_id}.state.json".to_owned(),
        snapshot_path_template: "{snapshot_id}.snapshot.json".to_owned(),
        skill_lean_case_template: "{agent_id}_{tool_name}_{ts}.json".to_owned(),
        agent_session_template: "{ts}_{prefix}.json".to_owned(),
    }
}

/// Deployment signals used by automatic mode detection.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeployDetection {
    /// Explicit `PRAXIS_DEPLOY_MODE` value, when supplied.
    pub override_mode: String,
    /// Container marker.
    pub docker: bool,
    /// Frozen executable marker.
    pub frozen: bool,
    /// IDE integration marker.
    pub ide: bool,
    /// Installed package marker.
    pub package_installed: bool,
}

/// Detect deployment mode from adapter-provided markers.
pub fn detect_deploy_mode(markers: &DeployDetection) -> DeployMode {
    if !markers.override_mode.is_empty() {
        let parsed = DeployMode::parse(&markers.override_mode);
        if markers.override_mode.eq_ignore_ascii_case(parsed.as_str()) {
            return parsed;
        }
    }
    if markers.docker {
        DeployMode::Docker
    } else if markers.frozen {
        DeployMode::Binary
    } else if markers.ide {
        DeployMode::IdePlugin
    } else if markers.package_installed {
        DeployMode::PipPackage
    } else {
        DeployMode::CliProject
    }
}

/// Resettable in-memory path store; environment discovery remains outside it.
pub struct PathStore {
    current: Mutex<Option<PraxisPaths>>,
}

impl PathStore {
    /// Create an empty path store.
    pub const fn new() -> Self {
        Self {
            current: Mutex::new(None),
        }
    }

    /// Get the existing set or derive one from explicit inputs.
    pub fn get_or_init(&self, input: &PathInputs) -> PraxisPaths {
        let mut current = self.lock();
        current.get_or_insert_with(|| resolve_paths(input)).clone()
    }

    /// Replace the current set from explicit inputs.
    pub fn configure(&self, input: &PathInputs) -> PraxisPaths {
        let mut current = self.lock();
        let paths = resolve_paths(input);
        *current = Some(paths.clone());
        paths
    }

    /// Clear the current set.
    pub fn reset(&self) {
        *self.lock() = None;
    }

    fn lock(&self) -> MutexGuard<'_, Option<PraxisPaths>> {
        self.current.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for PathStore {
    fn default() -> Self {
        Self::new()
    }
}

fn skill_dirs(input: &PathInputs, data_dir: &str, separator: &str) -> Vec<String> {
    if !input.skill_dir_override.is_empty() {
        return vec![input.skill_dir_override.clone(), "config/skills".to_owned()];
    }
    match input.deploy_mode {
        DeployMode::CliProject => vec![
            "config/skills".to_owned(),
            ".praxis/skills".to_owned(),
            "skills".to_owned(),
            "skills/evolved".to_owned(),
            ".skills".to_owned(),
        ],
        DeployMode::Docker => vec![
            "/etc/praxis/skills".to_owned(),
            join(data_dir, "skills", separator),
        ],
        DeployMode::PipPackage => vec![
            join(data_dir, "skills", separator),
            join(&input.package_root, "skills", separator),
        ],
        DeployMode::Binary if !input.executable_dir.is_empty() => vec![
            join(&input.executable_dir, "skills", separator),
            join(data_dir, "skills", separator),
        ],
        _ => vec![join(data_dir, "skills", separator)],
    }
}

fn fallback<'a>(value: &'a str, default: &'a str) -> &'a str {
    if value.is_empty() { default } else { value }
}

fn join(root: &str, child: &str, separator: &str) -> String {
    if root.is_empty() {
        return child.replace('/', separator);
    }
    format!(
        "{}{}{}",
        root.trim_end_matches(['/', '\\']),
        separator,
        child.replace('/', separator)
    )
}

fn default_skill_scope() -> String {
    "project".to_owned()
}

#[cfg(test)]
mod tests {
    use serde::Deserialize;

    use super::{
        DeployDetection, DeployMode, PathInputs, PathStore, detect_deploy_mode, resolve_paths,
    };

    #[derive(Debug, Deserialize)]
    struct PathVector {
        input: PathInputs,
        expected: serde_json::Value,
    }

    #[test]
    fn cli_paths_preserve_project_relative_contract() {
        let paths = resolve_paths(&PathInputs::cli("/home/user", "/workspace/praxis", "/tmp"));
        assert_eq!(paths.deploy_mode, DeployMode::CliProject);
        assert_eq!(paths.data_dir, ".praxis");
        assert_eq!(paths.config_dir, ".config/praxis");
        assert_eq!(paths.config_file, "config/praxis.yaml");
        assert_eq!(paths.events_db, ".praxis/events.db");
        assert_eq!(
            paths.skill_project_evolved_dir,
            "/workspace/praxis/skills/evolved"
        );
        assert_eq!(paths.vfs_temp_path, "/tmp");
    }

    #[test]
    fn docker_and_windows_defaults_are_explicit() {
        let mut input = PathInputs::cli("C:\\Users\\U", "C:\\Praxis", "C:\\Temp");
        input.deploy_mode = DeployMode::Docker;
        input.is_windows = true;
        input.path_separator = "\\".to_owned();
        input.appdata_dir = "C:\\Users\\U\\AppData\\Roaming".to_owned();
        let paths = resolve_paths(&input);
        assert_eq!(paths.data_dir, "/var/praxis");
        assert_eq!(paths.install_dir, "/app");
        assert_eq!(paths.config_dir, "/var/praxis");
        assert_eq!(
            paths.skill_dirs,
            ["/etc/praxis/skills", "/var/praxis\\skills"]
        );
    }

    #[test]
    fn mode_detection_prefers_valid_override_then_markers() {
        assert_eq!(
            detect_deploy_mode(&DeployDetection {
                override_mode: "pip".to_owned(),
                docker: true,
                ..Default::default()
            }),
            DeployMode::PipPackage
        );
        assert_eq!(
            detect_deploy_mode(&DeployDetection {
                override_mode: "unknown".to_owned(),
                docker: true,
                ..Default::default()
            }),
            DeployMode::Docker
        );
        assert_eq!(
            detect_deploy_mode(&DeployDetection {
                frozen: true,
                ide: true,
                ..Default::default()
            }),
            DeployMode::Binary
        );
    }

    #[test]
    fn path_store_configure_and_reset_do_not_touch_disk() {
        let store = PathStore::new();
        let first = store.get_or_init(&PathInputs::cli("/home/user", "/workspace/praxis", "/tmp"));
        let second = store.get_or_init(&PathInputs {
            data_dir_override: "/other".to_owned(),
            ..PathInputs::cli("/home/user", "/workspace/praxis", "/tmp")
        });
        assert_eq!(first, second);
        let configured = store.configure(&PathInputs {
            data_dir_override: "/other".to_owned(),
            ..PathInputs::cli("/home/user", "/workspace/praxis", "/tmp")
        });
        assert_eq!(configured.data_dir, "/other");
        store.reset();
        assert_eq!(
            store
                .get_or_init(&PathInputs::cli("/home/user", "/workspace/praxis", "/tmp"))
                .data_dir,
            ".praxis"
        );
    }

    #[test]
    fn shared_path_vectors_match_python_reference() {
        let vectors: Vec<PathVector> = serde_json::from_str(include_str!(
            "../../../tests/fixtures/kernel_paths_vectors.json"
        ))
        .expect("path fixture must be valid JSON");
        let fields = [
            "data_dir",
            "config_dir",
            "config_file",
            "install_dir",
            "config_templates_dir",
            "logs_dir",
            "skill_dirs",
            "skill_evolved_dir",
            "skill_project_evolved_dir",
            "events_db",
            "sandbox_root",
            "socket_dir",
            "todo_dir",
            "cell_state_template",
            "mute_state",
            "mode_state",
            "todo_state",
            "sandbox_state",
            "todo_table",
            "memory_persist_ring2",
            "memory_persist_ring3",
            "sandbox_state_template",
            "snapshot_path_template",
            "skill_lean_case_template",
            "agent_session_template",
        ];
        for vector in vectors {
            let actual = resolve_paths(&vector.input).to_json();
            for field in fields {
                assert_eq!(
                    actual[field], vector.expected[field],
                    "path vector field {field}"
                );
            }
        }
    }
}
