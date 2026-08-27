//! Run the independent Rust kernel assembly boundary.
//!
//! The state root is an explicit host argument. This binary does not infer a
//! working-directory-relative root or inspect host configuration.

use std::env;
use std::process::ExitCode;

use l1_kernel_rs::assembly::{AssemblySpec, KernelAssembly};
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::ports::{PortDescriptor, PortKind};

fn usage() -> &'static str {
    "usage: rust-kernel <state-root> [config-root]"
}

fn main() -> ExitCode {
    let mut args = env::args();
    let _program = args.next();
    let Some(state_root) = args.next() else {
        eprintln!("{}", usage());
        return ExitCode::FAILURE;
    };
    let config_root = args.next();
    if args.next().is_some() {
        eprintln!("{}", usage());
        return ExitCode::FAILURE;
    }
    let spec = AssemblySpec::new(
        state_root,
        vec![
            BootStepSpec::new("config", Vec::new()),
            BootStepSpec::new("services", vec!["config".to_owned()]),
            BootStepSpec::new("cell", vec!["services".to_owned()]),
        ],
        vec![
            PortDescriptor::new("process", PortKind::Process, 1),
            PortDescriptor::new("storage", PortKind::Storage, 1),
            PortDescriptor::new("scheduler", PortKind::Scheduler, 1),
            PortDescriptor::new("terminal", PortKind::Terminal, 1),
        ],
    );
    let spec = if let Some(root) = config_root {
        spec.with_config_root(root)
    } else {
        spec
    };
    let assembly = match KernelAssembly::assemble(spec) {
        Ok(assembly) => assembly,
        Err(error) => {
            eprintln!("rust kernel assembly rejected: {error:?}");
            return ExitCode::FAILURE;
        }
    };
    match serde_json::to_string(&assembly.snapshot()) {
        Ok(snapshot) => {
            println!("{snapshot}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("rust kernel assembly serialization failed: {error}");
            ExitCode::FAILURE
        }
    }
}
