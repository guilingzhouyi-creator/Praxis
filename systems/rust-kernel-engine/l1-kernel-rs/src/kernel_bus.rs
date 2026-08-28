//! Provider-neutral SystemBus metadata, dependency planning, and state values.
//!
//! Component callbacks, event routing, health providers, child-bus ownership,
//! and thread or process lifecycle remain Python adapter responsibilities.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque};
use std::fmt;
use std::sync::{Mutex, MutexGuard, PoisonError};

use serde::{Deserialize, Serialize};

/// Default component protocol version for unspecified specs.
fn default_version() -> String {
    "0.1.0".to_owned()
}

/// Declarative metadata for one bus-managed component.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComponentSpec {
    /// Stable component name supplied by the Python adapter.
    pub name: String,
    /// Component version.
    #[serde(default = "default_version")]
    pub version: String,
    /// Human-readable description.
    #[serde(default)]
    pub description: String,
    /// Hard dependencies, retained in declaration order.
    #[serde(default)]
    pub depends_on: Vec<String>,
    /// Optional dependencies, retained in declaration order.
    #[serde(default)]
    pub optional_deps: Vec<String>,
    /// Classification tags, retained in declaration order.
    #[serde(default)]
    pub tags: Vec<String>,
}

impl Default for ComponentSpec {
    /// Create an empty component spec.
    fn default() -> Self {
        Self {
            name: String::new(),
            version: default_version(),
            description: String::new(),
            depends_on: Vec::new(),
            optional_deps: Vec::new(),
            tags: Vec::new(),
        }
    }
}

/// Lifecycle state mirrored from Python's SystemBus state map.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ComponentState {
    /// Registered but not initialized.
    Registered,
    /// `bus_init` completed in the Python owner.
    Inited,
    /// `bus_start` completed in the Python owner.
    Started,
    /// `bus_stop` completed in the Python owner.
    Stopped,
}

impl ComponentState {
    /// Return the Python-compatible state spelling.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Registered => "registered",
            Self::Inited => "inited",
            Self::Started => "started",
            Self::Stopped => "stopped",
        }
    }
}

/// A deterministic dependency plan over one bus's registered components.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DependencyPlan {
    /// Component name to available dependency names.
    pub graph: BTreeMap<String, Vec<String>>,
    /// Stable Kahn order using registration order as the tie breaker.
    pub order: Vec<String>,
}

/// Structured planning failures.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BusPlanError {
    /// A component declared no name.
    EmptyName,
    /// A component name contains a NUL byte.
    InvalidName,
    /// The dependency graph contains a cycle.
    Cycle(Vec<String>),
}

impl fmt::Display for BusPlanError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyName => write!(f, "component has empty name"),
            Self::InvalidName => write!(f, "component name contains NUL"),
            Self::Cycle(names) => write!(f, "circular dependency detected among: {names:?}"),
        }
    }
}

impl std::error::Error for BusPlanError {}

#[derive(Debug, Default)]
struct BusState {
    components: Vec<ComponentSpec>,
    /// Stable name-to-slot index; `components` remains the ordering source.
    indices: HashMap<String, usize>,
    states: BTreeMap<String, ComponentState>,
}

/// Ordered component metadata table with explicit lifecycle markers.
pub struct ComponentRegistry {
    state: Mutex<BusState>,
}

impl ComponentRegistry {
    /// Create an empty component table.
    pub fn new() -> Self {
        Self {
            state: Mutex::new(BusState::default()),
        }
    }

    /// Register or replace metadata while preserving the original position.
    ///
    /// # Errors
    ///
    /// BusError on duplicate component registration or invalid metadata.
    pub fn register(&self, spec: ComponentSpec) -> Result<(), BusPlanError> {
        if spec.name.trim().is_empty() {
            return Err(BusPlanError::EmptyName);
        }
        if spec.name.contains('\0') {
            return Err(BusPlanError::InvalidName);
        }
        let mut state = self.lock_state();
        let name = spec.name.clone();
        if let Some(&index) = state.indices.get(&name) {
            state.components[index] = spec;
        } else {
            let index = state.components.len();
            state.indices.insert(name.clone(), index);
            state.components.push(spec);
        }
        state.states.insert(name, ComponentState::Registered);
        Ok(())
    }

    /// Return component names in registration order.
    pub fn names(&self) -> Vec<String> {
        self.lock_state()
            .components
            .iter()
            .map(|component| component.name.clone())
            .collect()
    }

    /// Return one cloned metadata record.
    pub fn get(&self, name: &str) -> Option<ComponentSpec> {
        let state = self.lock_state();
        state
            .indices
            .get(name)
            .and_then(|&index| state.components.get(index))
            .cloned()
    }

    /// Build the available-dependency graph and stable topological order.
    ///
    /// # Errors
    ///
    /// BusError when dependency filtering yields an unresolvable cycle.
    pub fn plan(&self, available: &[String]) -> Result<DependencyPlan, BusPlanError> {
        let state = self.lock_state();
        let names = state
            .components
            .iter()
            .map(|component| component.name.clone())
            .collect::<Vec<_>>();
        let local = names.iter().cloned().collect::<BTreeSet<_>>();
        let external = available.iter().cloned().collect::<BTreeSet<_>>();
        let mut graph = BTreeMap::new();
        for component in &state.components {
            let mut dependencies = Vec::new();
            for dependency in component
                .depends_on
                .iter()
                .chain(component.optional_deps.iter())
            {
                if local.contains(dependency) || external.contains(dependency) {
                    dependencies.push(dependency.clone());
                }
            }
            graph.insert(component.name.clone(), dependencies);
        }
        let order = topological_sort(&names, &graph)?;
        Ok(DependencyPlan { graph, order })
    }

    /// Mark a registered component as initialized.
    pub fn mark_inited(&self, name: &str) -> bool {
        let mut state = self.lock_state();
        if state.states.get(name) != Some(&ComponentState::Registered) {
            return false;
        }
        state.states.insert(name.to_owned(), ComponentState::Inited);
        true
    }

    /// Mark an initialized component as started.
    pub fn mark_started(&self, name: &str) -> bool {
        let mut state = self.lock_state();
        if state.states.get(name) != Some(&ComponentState::Inited) {
            return false;
        }
        state
            .states
            .insert(name.to_owned(), ComponentState::Started);
        true
    }

    /// Mark an initialized or started component as stopped.
    pub fn mark_stopped(&self, name: &str) -> bool {
        let mut state = self.lock_state();
        if !matches!(
            state.states.get(name),
            Some(ComponentState::Inited | ComponentState::Started)
        ) {
            return false;
        }
        state
            .states
            .insert(name.to_owned(), ComponentState::Stopped);
        true
    }

    /// Return Python-compatible state labels keyed by component name.
    pub fn state_map(&self) -> BTreeMap<String, String> {
        self.lock_state()
            .states
            .iter()
            .map(|(name, state)| (name.clone(), state.as_str().to_owned()))
            .collect()
    }

    fn lock_state(&self) -> MutexGuard<'_, BusState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for ComponentRegistry {
    /// Create an empty component registry.
    fn default() -> Self {
        Self::new()
    }
}

/// Linearize components by dependency order, fail-closed on cycles.
fn topological_sort(
    names: &[String],
    graph: &BTreeMap<String, Vec<String>>,
) -> Result<Vec<String>, BusPlanError> {
    // Build reverse edges once. The former implementation rescanned every
    // component after each pop, which made a long registry quadratic.
    // Registration order remains the tie breaker because both the outer build
    // loop and each dependent list follow `names`.
    let indexes = names
        .iter()
        .enumerate()
        .map(|(index, name)| (name.as_str(), index))
        .collect::<HashMap<_, _>>();
    let mut in_degree = vec![0_usize; names.len()];
    let mut dependents = vec![Vec::<usize>::new(); names.len()];
    for (candidate, name) in names.iter().enumerate() {
        let Some(dependencies) = graph.get(name) else {
            continue;
        };
        // A dependency declared in both hard and optional lists is one graph
        // edge. Preserve the public graph declaration, but do not let a
        // duplicate edge manufacture a false cycle.
        let mut seen = HashSet::new();
        for dependency in dependencies {
            let Some(&dependency_index) = indexes.get(dependency.as_str()) else {
                continue;
            };
            if !seen.insert(dependency_index) {
                continue;
            }
            in_degree[candidate] += 1;
            dependents[dependency_index].push(candidate);
        }
    }
    let mut queue = names
        .iter()
        .enumerate()
        .filter(|(index, _)| in_degree[*index] == 0)
        .map(|(index, _)| index)
        .collect::<VecDeque<_>>();
    let mut order = Vec::with_capacity(names.len());
    let mut emitted = vec![false; names.len()];
    while let Some(index) = queue.pop_front() {
        emitted[index] = true;
        order.push(names[index].clone());
        for &candidate in &dependents[index] {
            in_degree[candidate] = in_degree[candidate].saturating_sub(1);
            if in_degree[candidate] == 0 {
                queue.push_back(candidate);
            }
        }
    }
    if order.len() != names.len() {
        let cycle = names
            .iter()
            .enumerate()
            .filter(|(index, _)| !emitted[*index])
            .map(|(_, name)| name)
            .cloned()
            .collect();
        return Err(BusPlanError::Cycle(cycle));
    }
    Ok(order)
}
