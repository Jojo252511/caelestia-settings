//! Core logic for caelestia-settings, exposed to Python via PyO3 (later).
//!
//! This crate contains no GTK/UI code. Each migrated module lives in its
//! own file (e.g. `keybinds.rs`) and is unit-tested with `cargo test`.

pub mod keybinds;
pub mod rules;
