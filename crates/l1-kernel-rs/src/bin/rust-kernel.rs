//! Run the independent Rust kernel assembly boundary.

use l1_kernel_rs::assembly::{AssemblySpec, KernelAssembly};
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::ports::{PortDescriptor, PortKind};

fn main() {
    let spec = AssemblySpec::new(
        "state",
        vec![
            BootStepSpec::new("config", Vec::new()),
            BootStepSpec::new("services", vec!["config".to_owned()]),
            BootStepSpec::new("cell", vec!["services".to_owned()]),
        ],
        vec![
            PortDescriptor::new("process", PortKind::Process, 1),
            PortDescriptor::new("storage", PortKind::Storage, 1),
            PortDescriptor::new("scheduler", PortKind::Scheduler, 1),
        ],
    );
    let assembly = KernelAssembly::assemble(spec).expect("Rust kernel assembly is valid");
    println!(
        "{}",
        serde_json::to_string(&assembly.snapshot()).expect("assembly snapshot serializes")
    );
}
