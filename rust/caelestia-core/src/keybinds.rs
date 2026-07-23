//! Parsing of Hyprland keybinds.conf and variables.conf.
//!
//! Pure string-in / data-out functions: no file I/O here, so everything
//! is unit-testable without touching the filesystem. Thin I/O wrappers
//! come later, together with the PyO3 bindings.

use std::collections::HashMap;

/// Variables can reference each other ($mainMod = $superKey); we resolve
/// nested references iteratively and this bound keeps cycles from looping
/// forever (same limit as the Python original).
const MAX_RESOLVE_PASSES: usize = 5;

/// Parses all `$name = value` lines from variables.conf content and
/// resolves nested references between them.
pub fn parse_variables(input: &str) -> HashMap<String, String> {
    let mut variables = HashMap::new();

    for line in input.lines() {
        let Some((name, value)) = parse_variable_line(line) else {
            continue; // not a variable definition — skip
        };
        variables.insert(name.to_string(), value.to_string());
    }

    resolve_nested(&mut variables);
    variables
}

/// Extracts `(name, value)` from a single `$name = value  # comment` line.
/// Returns `None` for anything that is not a variable definition.
fn parse_variable_line(line: &str) -> Option<(&str, &str)> {
    let rest = line.trim_start().strip_prefix('$')?;

    // The name is the leading run of [A-Za-z0-9_] characters.
    let name_len = rest
        .find(|c: char| !c.is_ascii_alphanumeric() && c != '_')
        .unwrap_or(rest.len());
    if name_len == 0 {
        return None;
    }
    let (name, rest) = rest.split_at(name_len);

    let value = rest.trim_start().strip_prefix('=')?;

    // Cut a trailing `# comment` before trimming.
    let value = match value.find('#') {
        Some(idx) => &value[..idx],
        None => value,
    };
    Some((name, value.trim()))
}

/// Replaces every `$name` occurrence in `raw` with its value.
///
/// Longer names are substituted first so that `$mainMod2` is never
/// clobbered by a `$mainMod` replacement. (The Python original depends on
/// dict insertion order here; HashMap iteration order is random, so we
/// make the order explicit instead.)
pub fn resolve(raw: &str, variables: &HashMap<String, String>) -> String {
    let mut names: Vec<&String> = variables.keys().collect();
    names.sort_by_key(|name| std::cmp::Reverse(name.len()));

    let mut result = raw.trim().to_string();
    for name in names {
        result = result.replace(&format!("${name}"), &variables[name]);
    }
    result
}

/// Resolves variables that reference other variables, iterating until
/// nothing changes anymore (or the pass limit is hit for cyclic defs).
fn resolve_nested(variables: &mut HashMap<String, String>) {
    for _ in 0..MAX_RESOLVE_PASSES {
        // We cannot read the map while mutating its values (the borrow
        // checker forbids a shared + exclusive borrow at once), so each
        // pass resolves against a snapshot of the previous state.
        let snapshot = variables.clone();
        let mut changed = false;

        for value in variables.values_mut() {
            let resolved = resolve(value, &snapshot);
            if *value != resolved {
                *value = resolved;
                changed = true;
            }
        }

        if !changed {
            break;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_simple_variable() {
        let vars = parse_variables("$mainMod = SUPER");
        assert_eq!(vars["mainMod"], "SUPER");
    }

    #[test]
    fn ignores_non_variable_lines_and_comments() {
        let input = "\
# a comment
bind = SUPER, T, exec, kitty
$term = kitty  # my terminal
$ = broken
";
        let vars = parse_variables(input);
        assert_eq!(vars.len(), 1);
        assert_eq!(vars["term"], "kitty");
    }

    #[test]
    fn resolves_nested_variables() {
        let input = "\
$superKey = SUPER
$mainMod = $superKey
$comboMod = $mainMod SHIFT
";
        let vars = parse_variables(input);
        assert_eq!(vars["mainMod"], "SUPER");
        assert_eq!(vars["comboMod"], "SUPER SHIFT");
    }

    #[test]
    fn longer_names_win_over_prefixes() {
        let mut vars = HashMap::new();
        vars.insert("mod".to_string(), "SUPER".to_string());
        vars.insert("mod2".to_string(), "ALT".to_string());
        assert_eq!(resolve("$mod2 $mod", &vars), "ALT SUPER");
    }

    #[test]
    fn survives_cyclic_definitions() {
        let input = "\
$a = $b
$b = $a
";
        // Must terminate; the exact leftover value does not matter.
        let vars = parse_variables(input);
        assert_eq!(vars.len(), 2);
    }

    #[test]
    fn resolve_trims_input() {
        let vars = HashMap::new();
        assert_eq!(resolve("  SUPER  ", &vars), "SUPER");
    }
}
