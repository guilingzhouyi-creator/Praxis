//! Independent provider-neutral VFS mechanism tests for the Rust kernel.

use l1_kernel_rs::vfs::{
    MountPoint, MountType, VFS_DEFAULT_MIN_RING, Vfs, VfsConfig, VfsErrorCode,
};
use serde::Deserialize;
use std::time::Duration;

#[test]
fn longest_prefix_resolution_returns_structured_metadata() {
    let vfs = Vfs::new();
    vfs.mount(MountPoint::new("/project", MountType::Project).with_real_path("/srv/project"))
        .expect("project mount");
    vfs.mount(
        MountPoint::new(
            "/project/systems/python-reference-runtime",
            MountType::Sandbox,
        )
        .with_real_path("/srv/systems/python-reference-runtime"),
    )
    .expect("source mount");
    let resolved = vfs
        .resolve_mount("/project/systems/python-reference-runtime/main.py")
        .expect("resolution");
    assert_eq!(resolved.mount, "/project/systems/python-reference-runtime");
    assert_eq!(resolved.rel, "main.py");
    assert_eq!(
        resolved.real_path,
        "/srv/systems/python-reference-runtime/main.py"
    );
    assert_eq!(resolved.min_ring, VFS_DEFAULT_MIN_RING);
}

#[test]
fn mount_table_is_bounded_and_duplicate_mounts_fail_closed() {
    let vfs = Vfs::with_config(VfsConfig {
        max_mounts: 1,
        ..VfsConfig::default()
    });
    vfs.mount(MountPoint::new("/one", MountType::Project))
        .expect("mount");
    assert_eq!(
        vfs.mount(MountPoint::new("/one", MountType::Project))
            .expect_err("duplicate")
            .code,
        VfsErrorCode::DuplicateMount
    );
    assert_eq!(
        vfs.mount(MountPoint::new("/two", MountType::Project))
            .expect_err("capacity")
            .code,
        VfsErrorCode::Capacity
    );
}

#[test]
fn virtual_storage_enforces_ring_read_only_and_unlink() {
    let vfs = Vfs::new();
    vfs.mount(
        MountPoint::new("/virtual", MountType::Virtual)
            .with_min_ring(2)
            .with_read_only(false),
    )
    .expect("virtual mount");
    assert_eq!(
        vfs.write("/virtual/note.txt", "hello", 1)
            .expect_err("ring")
            .code,
        VfsErrorCode::PermissionDenied
    );
    vfs.write("/virtual/note.txt", "hello", 2).expect("write");
    let read = vfs.read("/virtual/note.txt", 2).expect("read");
    assert_eq!(read.content, "hello");
    assert!(!read.cached);
    assert!(vfs.unlink("/virtual/note.txt", 2).is_ok());
    assert_eq!(
        vfs.read("/virtual/note.txt", 2).expect_err("deleted").code,
        VfsErrorCode::NotFound
    );
}

#[test]
fn virtual_store_is_bounded_oldest_first_and_lists_deterministically() {
    let vfs = Vfs::with_config(VfsConfig {
        virtual_capacity: 2,
        ..VfsConfig::default()
    });
    vfs.mount(MountPoint::new("/virtual", MountType::Virtual))
        .expect("mount");
    vfs.write("/virtual/b", "b", 1).expect("b");
    vfs.write("/virtual/a", "a", 1).expect("a");
    vfs.write("/virtual/c", "c", 1).expect("c");
    assert_eq!(
        vfs.read("/virtual/b", 1).expect_err("evicted").code,
        VfsErrorCode::NotFound
    );
    assert_eq!(
        vfs.list_dir("/virtual", 1).expect("listing").entries,
        vec!["/virtual/a", "/virtual/c"]
    );
    assert_eq!(vfs.stats().virtual_files, 2);
}

#[test]
fn read_only_and_low_ring_are_checked_before_provider_boundary() {
    let vfs = Vfs::new();
    vfs.mount(
        MountPoint::new("/project", MountType::Project)
            .with_min_ring(3)
            .with_read_only(true),
    )
    .expect("project mount");
    assert_eq!(
        vfs.read_from_provider("/project/x", "x", 1)
            .expect_err("ring")
            .code,
        VfsErrorCode::PermissionDenied
    );
    assert_eq!(
        vfs.write("/project/x", "x", 3).expect_err("read only").code,
        VfsErrorCode::ReadOnly
    );
    assert_eq!(
        vfs.read("/project/x", 3).expect_err("provider").code,
        VfsErrorCode::ProviderRequired
    );
}

#[test]
fn provider_reads_use_bounded_ttl_cache_and_invalidation() {
    let vfs = Vfs::with_config(VfsConfig {
        cache_capacity: 2,
        cache_ttl: Duration::from_secs(60),
        ..VfsConfig::default()
    });
    vfs.mount(MountPoint::new("/project", MountType::Project))
        .expect("mount");
    let first = vfs
        .read_from_provider("/project/a", "v1", 1)
        .expect("first");
    assert!(!first.cached);
    let cached = vfs
        .read_from_provider("/project/a", "v2", 1)
        .expect("cached");
    assert!(cached.cached);
    assert_eq!(cached.content, "v1");
    vfs.invalidate_cache("/project/a").expect("invalidate");
    let refreshed = vfs
        .read_from_provider("/project/a", "v2", 1)
        .expect("refresh");
    assert!(!refreshed.cached);
    assert_eq!(refreshed.content, "v2");
}

#[test]
fn zero_ttl_disables_cache_and_invalid_paths_are_rejected() {
    let vfs = Vfs::with_config(VfsConfig {
        cache_ttl: Duration::ZERO,
        ..VfsConfig::default()
    });
    vfs.mount(MountPoint::new("/project", MountType::Project))
        .expect("mount");
    assert!(
        !vfs.read_from_provider("/project/a", "v1", 1)
            .expect("read")
            .cached
    );
    assert!(
        !vfs.read_from_provider("/project/a", "v2", 1)
            .expect("read")
            .cached
    );
    assert_eq!(
        vfs.resolve_mount("/project/../escape")
            .expect_err("path")
            .code,
        VfsErrorCode::InvalidPath
    );
    assert_eq!(
        vfs.resolve_mount("relative").expect_err("path").code,
        VfsErrorCode::InvalidPath
    );
}

#[test]
fn provider_listing_is_sorted_and_virtual_provider_is_rejected() {
    let vfs = Vfs::new();
    vfs.mount(MountPoint::new("/project", MountType::Project))
        .expect("mount");
    assert_eq!(
        vfs.list_from_provider("/project", vec!["z.txt".to_owned(), "a.txt".to_owned()], 1)
            .expect("listing")
            .entries,
        vec!["a.txt", "z.txt"]
    );
    vfs.mount(MountPoint::new("/virtual", MountType::Virtual))
        .expect("virtual");
    assert_eq!(
        vfs.read_from_provider("/virtual/a", "a", 1)
            .expect_err("provider")
            .code,
        VfsErrorCode::ProviderRequired
    );
}

#[derive(Deserialize)]
struct Vector {
    mounts: Vec<MountVector>,
    path: String,
    expect: Option<ExpectedResolution>,
}

#[derive(Deserialize)]
struct MountVector {
    name: String,
    mount_type: String,
    real_path: String,
    min_ring: u8,
    read_only: bool,
}

#[derive(Deserialize, PartialEq, Eq, Debug)]
struct ExpectedResolution {
    mount: String,
    rel: String,
    root: String,
    real_path: String,
    min_ring: u8,
    read_only: bool,
}

#[test]
fn shared_mount_resolution_vectors_match_python_reference() {
    let vectors: Vec<Vector> = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_vfs_vectors.json"
    ))
    .expect("vfs fixture");
    for vector in vectors {
        let vfs = Vfs::new();
        for mount in vector.mounts {
            let mount_type = match mount.mount_type.as_str() {
                "PROJECT" => MountType::Project,
                "SANDBOX" => MountType::Sandbox,
                "TEMP" => MountType::Temp,
                "VIRTUAL" => MountType::Virtual,
                "SYSTEM" => MountType::System,
                other => panic!("unknown mount type {other}"),
            };
            vfs.mount(
                MountPoint::new(mount.name, mount_type)
                    .with_real_path(mount.real_path)
                    .with_min_ring(mount.min_ring)
                    .with_read_only(mount.read_only),
            )
            .expect("mount");
        }
        let actual = vfs
            .resolve_mount(&vector.path)
            .ok()
            .map(|resolved| ExpectedResolution {
                mount: resolved.mount,
                rel: resolved.rel,
                root: resolved.root,
                real_path: resolved.real_path,
                min_ring: resolved.min_ring,
                read_only: resolved.read_only,
            });
        assert_eq!(actual, vector.expect);
    }
}

#[test]
fn root_mount_resolution_handles_relative_paths() {
    let vfs = Vfs::new();
    vfs.mount(MountPoint::new("/", MountType::Virtual))
        .expect("root mount");
    vfs.write("/note.txt", "note", 1).expect("write");
    let resolved = vfs.resolve_mount("/note.txt").expect("resolve");
    assert_eq!(resolved.mount, "/");
    assert_eq!(resolved.rel, "note.txt");
    assert_eq!(vfs.read("/note.txt", 1).expect("read").content, "note");
}
