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

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString};

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
// lua.rs — Lua config codec (app-controlled subset)
// ---------------------------------------------------------------------

/// Converts a parsed `caelestia_core::lua::LuaValue` into a native Python
/// object: `Nil` -> `None`, `Bool` -> `bool`, `Number` -> `int`/`float`
/// (falling back to `str` if somehow neither parses, which should not
/// happen for anything this codec itself produced), `Str` -> `str`,
/// `Table` -> `list` if every entry is positional, otherwise `dict`
/// (missing keys among mixed entries get a synthetic `_<n>` key rather
/// than silently dropping the value).
fn lua_value_to_py(py: Python<'_>, v: &caelestia_core::lua::LuaValue) -> PyResult<Py<PyAny>> {
    use caelestia_core::lua::LuaValue;
    Ok(match v {
        LuaValue::Nil => py.None(),
        LuaValue::Bool(b) => b.into_pyobject(py)?.to_owned().into_any().unbind(),
        LuaValue::Number(s) => {
            if let Ok(i) = s.parse::<i64>() {
                i.into_pyobject(py)?.into_any().unbind()
            } else if let Ok(f) = s.parse::<f64>() {
                f.into_pyobject(py)?.into_any().unbind()
            } else {
                s.into_pyobject(py)?.into_any().unbind()
            }
        }
        LuaValue::Str(s) => s.into_pyobject(py)?.into_any().unbind(),
        LuaValue::Table(entries) => {
            if entries.iter().all(|(k, _)| k.is_none()) {
                let list = PyList::empty(py);
                for (_, val) in entries {
                    list.append(lua_value_to_py(py, val)?)?;
                }
                list.into_any().unbind()
            } else {
                let dict = PyDict::new(py);
                for (i, (k, val)) in entries.iter().enumerate() {
                    let key = k.clone().unwrap_or_else(|| format!("_{}", i + 1));
                    dict.set_item(key, lua_value_to_py(py, val)?)?;
                }
                dict.into_any().unbind()
            }
        }
    })
}

/// Converts a native Python object back into a `LuaValue` for rendering.
/// Only the JSON-like subset this codec understands is accepted: `None`,
/// `bool`, `int`, `float`, `str`, `list`/`tuple` (-> positional table),
/// `dict` with string keys (-> keyed table). Anything else raises
/// `ValueError` rather than guessing.
fn py_to_lua_value(value: &Bound<'_, PyAny>) -> PyResult<caelestia_core::lua::LuaValue> {
    use caelestia_core::lua::LuaValue;

    if value.is_none() {
        return Ok(LuaValue::Nil);
    }
    if let Ok(b) = value.cast::<PyBool>() {
        return Ok(LuaValue::Bool(b.is_true()));
    }
    if let Ok(i) = value.cast::<PyInt>() {
        return Ok(LuaValue::Number(i.to_string()));
    }
    if let Ok(f) = value.cast::<PyFloat>() {
        let n = f.value();
        let mut s = n.to_string();
        if !s.contains('.') {
            s.push_str(".0");
        }
        return Ok(LuaValue::Number(s));
    }
    if let Ok(s) = value.cast::<PyString>() {
        return Ok(LuaValue::Str(s.to_string()));
    }
    if let Ok(dict) = value.cast::<PyDict>() {
        let mut entries = Vec::with_capacity(dict.len());
        for (k, v) in dict.iter() {
            let key: String = k
                .extract()
                .map_err(|_| PyValueError::new_err("Lua table keys must be strings"))?;
            entries.push((Some(key), py_to_lua_value(&v)?));
        }
        return Ok(LuaValue::Table(entries));
    }
    if let Ok(list) = value.cast::<PyList>() {
        let mut entries = Vec::with_capacity(list.len());
        for item in list.iter() {
            entries.push((None, py_to_lua_value(&item)?));
        }
        return Ok(LuaValue::Table(entries));
    }
    if let Ok(tuple) = value.cast::<pyo3::types::PyTuple>() {
        let mut entries = Vec::with_capacity(tuple.len());
        for item in tuple.iter() {
            entries.push((None, py_to_lua_value(&item)?));
        }
        return Ok(LuaValue::Table(entries));
    }
    Err(PyValueError::new_err(format!(
        "unsupported Python type for Lua rendering: {}",
        value.get_type().name()?
    )))
}

/// `caelestia_core.parse_lua_table(input: str) -> dict | list`
///
/// Parses a single Lua table literal (e.g. the `{ ... }` argument of an
/// `hl.monitor({ ... })` call) into a native Python structure.
#[pyfunction]
fn parse_lua_table(py: Python<'_>, input: &str) -> PyResult<Py<PyAny>> {
    let value = caelestia_core::lua::parse_value(input)
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    lua_value_to_py(py, &value)
}

/// `caelestia_core.render_lua_table(value: dict | list) -> str`
///
/// The inverse of `parse_lua_table`: renders a Python dict/list back into
/// deterministic, single-line Lua table syntax.
#[pyfunction]
fn render_lua_table(value: &Bound<'_, PyAny>) -> PyResult<String> {
    let lua_value = py_to_lua_value(value)?;
    Ok(caelestia_core::lua::render_value(&lua_value))
}

/// `caelestia_core.parse_lua_call(input: str) -> tuple[str, list]`
///
/// Parses a call expression like `hl.monitor({ ... })` into its dotted
/// path (`"hl.monitor"`) and a list of its arguments, each converted the
/// same way `parse_lua_table` converts a table.
#[pyfunction]
fn parse_lua_call(py: Python<'_>, input: &str) -> PyResult<(String, Vec<Py<PyAny>>)> {
    let call =
        caelestia_core::lua::parse_call(input).map_err(|e| PyValueError::new_err(e.to_string()))?;
    let args = call
        .args
        .iter()
        .map(|a| lua_value_to_py(py, a))
        .collect::<PyResult<Vec<_>>>()?;
    Ok((call.path.join("."), args))
}

/// `caelestia_core.render_lua_call(path: str, args: list) -> str`
///
/// The inverse of `parse_lua_call`: `path` is a dot-joined identifier
/// chain (`"hl.monitor"`), `args` is a list of Python values each
/// converted the same way `render_lua_table` converts one.
#[pyfunction]
fn render_lua_call(path: &str, args: Vec<Bound<'_, PyAny>>) -> PyResult<String> {
    let path_parts: Vec<&str> = path.split('.').collect();
    let lua_args = args
        .iter()
        .map(py_to_lua_value)
        .collect::<PyResult<Vec<_>>>()?;
    Ok(caelestia_core::lua::render_call(&path_parts, &lua_args))
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

    m.add_function(wrap_pyfunction!(parse_lua_table, m)?)?;
    m.add_function(wrap_pyfunction!(render_lua_table, m)?)?;
    m.add_function(wrap_pyfunction!(parse_lua_call, m)?)?;
    m.add_function(wrap_pyfunction!(render_lua_call, m)?)?;

    Ok(())
}
