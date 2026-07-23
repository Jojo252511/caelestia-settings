//! PyO3 bindings that expose `caelestia-core`'s pure Rust logic as the
//! `caelestia_core` Python extension module.
//!
//! This crate is intentionally a *thin* wrapper: every function below
//! just converts between PyO3 types and `caelestia-core` types and calls
//! straight through. All real logic (parsing, conflict detection, PWM
//! math) stays in `caelestia-core`, which keeps being pure-Rust
//! unit-testable without Python or a compiled extension module anywhere
//! in the loop — this crate has no `#[cfg(test)]` of its own for that
//! reason; a successful `cargo build` / `maturin develop` *is* its test.

use std::collections::HashMap;

use pyo3::prelude::*;

// ---------------------------------------------------------------------
// keybinds.rs — variables.conf parsing
// ---------------------------------------------------------------------

/// `caelestia_core.parse_variables(input: str) -> dict[str, str]`
///
/// No wrapper type needed: PyO3 already knows how to turn a
/// `HashMap<String, String>` into a Python `dict` (it implements the
/// `IntoPyObject` conversion trait for any `HashMap<K, V>` whose `K`/`V`
/// do), so returning it straight from a `#[pyfunction]` just works.
#[pyfunction]
fn parse_variables(input: &str) -> HashMap<String, String> {
    caelestia_core::keybinds::parse_variables(input)
}

/// `caelestia_core.resolve(raw: str, variables: dict[str, str]) -> str`
///
/// The core function borrows its `variables` map (`&HashMap<...>`), but
/// the parameter type here is an *owned* `HashMap<String, String>`:
/// converting a Python `dict` means PyO3 must build a fresh Rust map
/// from the dict's entries — there's no way to borrow Python's internal
/// dict storage as a native Rust `HashMap`. We then just borrow our own
/// freshly built copy for the call.
#[pyfunction]
fn resolve(raw: &str, variables: HashMap<String, String>) -> String {
    caelestia_core::keybinds::resolve(raw, &variables)
}

// ---------------------------------------------------------------------
// config.rs — monitors.conf parsing
// ---------------------------------------------------------------------

/// Python-visible mirror of `caelestia_core::config::Monitor`.
///
/// A dedicated `#[pyclass]`, not a tuple or a `PyDict`: a tuple would
/// lose the field names (Python code would have to remember that index
/// 1 means "resolution"), and a dict loses static structure — a typo'd
/// or missing key only fails at runtime, on whatever line happens to
/// read it. A `#[pyclass]` gives Python callers `monitor.name` /
/// `monitor.resolution` with the same structure a Rust caller of
/// `caelestia-core` already gets from the struct itself, and every field
/// below is `#[pyo3(get)]`-only (no `set`): these values come out of a
/// parser, so Python code has no business mutating them after the fact.
#[pyclass]
struct Monitor {
    #[pyo3(get)]
    name: String,
    #[pyo3(get)]
    resolution: String,
    #[pyo3(get)]
    position: String,
    #[pyo3(get)]
    scale: String,
}

impl From<caelestia_core::config::Monitor> for Monitor {
    fn from(m: caelestia_core::config::Monitor) -> Self {
        Self {
            name: m.name,
            resolution: m.resolution,
            position: m.position,
            scale: m.scale,
        }
    }
}

/// Python-visible mirror of `caelestia_core::config::Workspace`.
/// See [`Monitor`] above for why this is a `#[pyclass]`.
#[pyclass]
struct Workspace {
    #[pyo3(get)]
    number: u32,
    #[pyo3(get)]
    monitor: String,
    #[pyo3(get)]
    default: bool,
}

impl From<caelestia_core::config::Workspace> for Workspace {
    fn from(w: caelestia_core::config::Workspace) -> Self {
        Self {
            number: w.number,
            monitor: w.monitor,
            default: w.default,
        }
    }
}

/// `caelestia_core.parse_monitors_conf(input: str) -> tuple[list[Monitor], list[Workspace]]`
///
/// `Vec<T>` converts to a Python `list` the same way `HashMap` converts
/// to a `dict` (an `IntoPyObject` impl PyO3 provides whenever `T` does,
/// which every `#[pyclass]` type does automatically) — and a Rust tuple
/// converts to a Python tuple the same way, so returning
/// `(Vec<Monitor>, Vec<Workspace>)` needs no manual packing at all.
#[pyfunction]
fn parse_monitors_conf(input: &str) -> (Vec<Monitor>, Vec<Workspace>) {
    let (monitors, workspaces) = caelestia_core::config::parse_monitors_conf(input);
    (
        monitors.into_iter().map(Monitor::from).collect(),
        workspaces.into_iter().map(Workspace::from).collect(),
    )
}

// ---------------------------------------------------------------------
// rules.rs — rules.conf parsing
// ---------------------------------------------------------------------

/// Python-visible mirror of `caelestia_core::rules::WindowRule`.
/// See [`Monitor`] above for why this is a `#[pyclass]`.
#[pyclass]
struct WindowRule {
    #[pyo3(get)]
    rule: String,
    #[pyo3(get)]
    match_type: String,
    #[pyo3(get)]
    match_val: String,
    #[pyo3(get)]
    raw: String,
    #[pyo3(get)]
    managed: bool,
}

impl From<caelestia_core::rules::WindowRule> for WindowRule {
    fn from(r: caelestia_core::rules::WindowRule) -> Self {
        Self {
            rule: r.rule,
            match_type: r.match_type,
            match_val: r.match_val,
            raw: r.raw,
            managed: r.managed,
        }
    }
}

/// `caelestia_core.parse_rules_conf(input: str) -> list[WindowRule]`
#[pyfunction]
fn parse_rules_conf(input: &str) -> Vec<WindowRule> {
    caelestia_core::rules::parse_rules_conf(input)
        .into_iter()
        .map(WindowRule::from)
        .collect()
}

// ---------------------------------------------------------------------
// window_rule_conflicts.rs — conflict detection
// ---------------------------------------------------------------------

/// Python-visible mirror of `caelestia_core::window_rule_conflicts::Conflict`.
/// See [`Monitor`] above for why this is a `#[pyclass]`.
#[pyclass]
struct Conflict {
    #[pyo3(get)]
    wm_class: String,
    #[pyo3(get)]
    first_workspace: String,
    #[pyo3(get)]
    conflicting_workspace: String,
}

impl From<caelestia_core::window_rule_conflicts::Conflict> for Conflict {
    fn from(c: caelestia_core::window_rule_conflicts::Conflict) -> Self {
        Self {
            wm_class: c.wm_class,
            first_workspace: c.first_workspace,
            conflicting_workspace: c.conflicting_workspace,
        }
    }
}

/// `caelestia_core.find_conflicts(rules: list[tuple[str, str]]) -> list[Conflict]`
///
/// PyO3 converts the Python list of 2-tuples into an *owned*
/// `Vec<(String, String)>` for us. The core function only ever reads
/// its input (`&[(&str, &str)]`), so — same borrow-not-clone principle
/// `caelestia-core` itself follows, just applied one layer up — we
/// borrow a `&str` view into each owned `String` before calling it,
/// rather than giving the core function ownership it doesn't need.
#[pyfunction]
fn find_conflicts(rules: Vec<(String, String)>) -> Vec<Conflict> {
    let borrowed: Vec<(&str, &str)> = rules
        .iter()
        .map(|(wm_class, workspace)| (wm_class.as_str(), workspace.as_str()))
        .collect();

    caelestia_core::window_rule_conflicts::find_conflicts(&borrowed)
        .into_iter()
        .map(Conflict::from)
        .collect()
}

// ---------------------------------------------------------------------
// fans.rs — PWM percent/raw conversion
// ---------------------------------------------------------------------

/// `caelestia_core.pwm_raw_to_percent(raw: int) -> int`
///
/// `u8` needs no wrapper at all: PyO3 converts a Python `int` to any
/// Rust integer type directly (raising `OverflowError` on the Python
/// side if the value doesn't fit in a `u8`), which is exactly the
/// 0..=255 validation this function's input needs — for free.
#[pyfunction]
fn pwm_raw_to_percent(raw: u8) -> u8 {
    caelestia_core::fans::pwm_raw_to_percent(raw)
}

/// `caelestia_core.percent_to_pwm_raw(percent: int) -> int`
#[pyfunction]
fn percent_to_pwm_raw(percent: u8) -> u8 {
    caelestia_core::fans::percent_to_pwm_raw(percent)
}

// ---------------------------------------------------------------------
// module registration
// ---------------------------------------------------------------------

/// The `#[pymodule]` function is what `import caelestia_core` actually
/// runs, once, at import time: it builds the module object and registers
/// every function/class that should be visible from Python. Anything not
/// added here (e.g. the wrapper structs' `From` impls, or any of
/// `caelestia-core`'s own items) simply does not exist on the Python
/// side, even though it is `pub`/visible from other Rust code.
///
/// Named `caelestia_core_pymodule`, *not* `caelestia_core`: the
/// `#[pymodule]` macro generates a crate-root item using the function's
/// own name, which would otherwise collide with — and shadow — the
/// extern crate path `caelestia_core::...` used everywhere above to
/// reach the `caelestia-core` dependency. `#[pyo3(name = "...")]` is
/// what actually controls the Python-visible name, independent of the
/// Rust identifier, so the collision is avoidable without renaming the
/// dependency or the Python module itself.
#[pymodule]
#[pyo3(name = "caelestia_core")]
fn caelestia_core_pymodule(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Monitor>()?;
    m.add_class::<Workspace>()?;
    m.add_class::<WindowRule>()?;
    m.add_class::<Conflict>()?;

    m.add_function(wrap_pyfunction!(parse_variables, m)?)?;
    m.add_function(wrap_pyfunction!(resolve, m)?)?;
    m.add_function(wrap_pyfunction!(parse_monitors_conf, m)?)?;
    m.add_function(wrap_pyfunction!(parse_rules_conf, m)?)?;
    m.add_function(wrap_pyfunction!(find_conflicts, m)?)?;
    m.add_function(wrap_pyfunction!(pwm_raw_to_percent, m)?)?;
    m.add_function(wrap_pyfunction!(percent_to_pwm_raw, m)?)?;

    Ok(())
}
