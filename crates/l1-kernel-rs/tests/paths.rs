//! Independent deployment-path mechanism tests for the Rust kernel.

use l1_kernel_rs::paths::{
    DeployDetection, DeployMode, PathInputs, PathStore, detect_deploy_mode, resolve_paths,
};
use serde::Deserialize;

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
