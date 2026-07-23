//! Parsing of Hyprland's monitors.conf (`monitor = ...` / `workspace = ...` lines).
//!
//! Pure string-in / data-out, same as `keybinds.rs`: no file I/O, no GTK
//! presentation logic (the `workspace_options` dropdown labels from the
//! Python original belong to the UI layer and are rebuilt on top of this
//! once the PyO3 bindings exist).

/// One `monitor = name,resolution,position,scale[,...]` line.
///
/// Hyprland allows further comma-separated fields after `scale` (bitdepth,
/// mirror target, vrr, ...); we don't expose those in the UI yet, so they
/// are parsed past and discarded rather than kept around unused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Monitor {
    pub name: String,
    pub resolution: String,
    pub position: String,
    pub scale: String,
}

/// One `workspace = number, monitor:NAME, default:true` line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Workspace {
    pub number: u32,
    pub monitor: String,
    pub default: bool,
}

/// Parses all `monitor` and `workspace` directive lines out of a
/// monitors.conf's contents. Everything else (comments, blank lines,
/// unrelated directives) is ignored.
///
/// Workspaces are returned sorted by `number`, matching the Python
/// original's `workspaces.sort(key=lambda w: w["number"])` — the file
/// itself has no guaranteed ordering since Hyprland doesn't require one.
pub fn parse_monitors_conf(input: &str) -> (Vec<Monitor>, Vec<Workspace>) {
    let mut monitors = Vec::new();
    let mut workspaces = Vec::new();

    for raw_line in input.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }

        if let Some(monitor) = parse_monitor_line(line) {
            monitors.push(monitor);
        } else if let Some(workspace) = parse_workspace_line(line) {
            workspaces.push(workspace);
        }
    }

    workspaces.sort_by_key(|w| w.number);
    (monitors, workspaces)
}

/// Extracts a [`Monitor`] from a single line, or `None` if the line is not
/// a `monitor` directive (wrong prefix) or has no `=` to split on.
///
/// Missing trailing fields fall back to the same placeholders the Python
/// original used, so an old/hand-written monitors.conf entry that only
/// specifies a name still parses instead of being dropped: `?` (unknown
/// resolution), `auto` (let Hyprland place it), `1` (no scaling).
fn parse_monitor_line(line: &str) -> Option<Monitor> {
    if !line.starts_with("monitor") {
        return None;
    }
    // split_once, not split(): a resolution/position string may itself
    // contain '=' in principle, and we only ever want the *first* split,
    // exactly like Python's `.split("=", 1)`.
    let (_, rest) = line.split_once('=')?;
    let mut fields = rest.split(',').map(str::trim);

    // The Python original does not validate that this first field is
    // non-empty either — a malformed `monitor = ,1920x1080` would produce
    // a `Monitor` with an empty name there too. We stay bug-compatible on
    // this specific point since it's a silent data-quality issue, not a
    // crash, and callers further up the stack already have to handle
    // unnamed/placeholder monitors.
    let name = fields.next()?.to_string();

    Some(Monitor {
        name,
        resolution: fields.next().unwrap_or("?").to_string(),
        position: fields.next().unwrap_or("auto").to_string(),
        scale: fields.next().unwrap_or("1").to_string(),
    })
}

/// Extracts a [`Workspace`] from a single line, or `None` if the line is
/// not a `workspace` directive, has no `=`, or has a non-numeric workspace
/// number.
///
/// The Python original wrapped the `int(tokens[0])` conversion in a
/// `try/except ValueError: continue`; `.parse().ok()?` is the direct Rust
/// equivalent — skip this one line, keep parsing the rest of the file.
fn parse_workspace_line(line: &str) -> Option<Workspace> {
    if !line.starts_with("workspace") {
        return None;
    }
    let (_, rest) = line.split_once('=')?;
    let mut tokens = rest.split(',').map(str::trim);

    let number: u32 = tokens.next()?.parse().ok()?;

    let mut monitor = String::new();
    let mut default = false;
    for tok in tokens {
        // `strip_prefix` here is the Rust equivalent of Python's
        // `tok.split("monitor:")[1]` — both just take what follows the
        // literal "monitor:", but strip_prefix also confirms it was
        // actually at the start of the token instead of anywhere in it.
        if let Some(name) = tok.strip_prefix("monitor:") {
            monitor = name.to_string();
        }
        // A `contains` check (not an exact match) on purpose: Hyprland's
        // own syntax examples write this token as `default:true`, but we
        // don't want a stray trailing flag glued onto the same token to
        // break detection, matching the Python original's `in` check.
        if tok.contains("default:true") {
            default = true;
        }
    }

    Some(Workspace {
        number,
        monitor,
        default,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_monitor_with_all_fields() {
        let (monitors, _) = parse_monitors_conf("monitor = DP-1,2560x1440@179.95,0x0,1");
        assert_eq!(
            monitors,
            vec![Monitor {
                name: "DP-1".to_string(),
                resolution: "2560x1440@179.95".to_string(),
                position: "0x0".to_string(),
                scale: "1".to_string(),
            }]
        );
    }

    #[test]
    fn monitor_missing_fields_fall_back_to_placeholders() {
        let (monitors, _) = parse_monitors_conf("monitor = DP-1");
        assert_eq!(
            monitors,
            vec![Monitor {
                name: "DP-1".to_string(),
                resolution: "?".to_string(),
                position: "auto".to_string(),
                scale: "1".to_string(),
            }]
        );
    }

    #[test]
    fn monitor_extra_trailing_fields_are_ignored() {
        let (monitors, _) = parse_monitors_conf("monitor = DP-1,2560x1440,0x0,1,bitdepth,10");
        assert_eq!(monitors[0].scale, "1");
    }

    #[test]
    fn parses_workspace_with_monitor_and_default() {
        let (_, workspaces) = parse_monitors_conf("workspace = 1, monitor:DP-1, default:true");
        assert_eq!(
            workspaces,
            vec![Workspace {
                number: 1,
                monitor: "DP-1".to_string(),
                default: true,
            }]
        );
    }

    #[test]
    fn workspace_without_default_flag_is_not_default() {
        let (_, workspaces) = parse_monitors_conf("workspace = 2, monitor:DP-2");
        assert!(!workspaces[0].default);
        assert_eq!(workspaces[0].monitor, "DP-2");
    }

    #[test]
    fn workspace_with_non_numeric_number_is_skipped() {
        let (_, workspaces) = parse_monitors_conf("workspace = special:music, monitor:DP-1");
        assert!(workspaces.is_empty());
    }

    #[test]
    fn workspaces_are_sorted_by_number() {
        let input = "\
workspace = 3, monitor:DP-1
workspace = 1, monitor:DP-2
workspace = 2, monitor:DP-1
";
        let (_, workspaces) = parse_monitors_conf(input);
        let numbers: Vec<u32> = workspaces.iter().map(|w| w.number).collect();
        assert_eq!(numbers, vec![1, 2, 3]);
    }

    #[test]
    fn blank_lines_and_comments_are_skipped() {
        let input = "\
# a comment

monitor = DP-1,2560x1440,0x0,1
";
        let (monitors, workspaces) = parse_monitors_conf(input);
        assert_eq!(monitors.len(), 1);
        assert!(workspaces.is_empty());
    }

    #[test]
    fn unrelated_directives_are_ignored() {
        let (monitors, workspaces) = parse_monitors_conf("input:kb_layout = us");
        assert!(monitors.is_empty());
        assert!(workspaces.is_empty());
    }
}
