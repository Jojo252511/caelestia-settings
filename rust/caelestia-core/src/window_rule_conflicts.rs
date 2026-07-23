//! Conflict detection for window rules: the same `wm_class` assigned to
//! two different workspaces across the rule list.
//!
//! Pure data-in / data-out, same as the other modules: no GTK, no I/O.
//! The caller (the `AppRuleRow` widgets in `window_rules.py`, later a thin
//! PyO3 wrapper) is responsible for turning live UI state into the
//! `(wm_class, workspace)` pairs this function reads.

use std::collections::HashMap;

/// One detected conflict: `wm_class` is assigned to `first_workspace` by
/// an earlier rule, then to `conflicting_workspace` by a later one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Conflict {
    pub wm_class: String,
    pub first_workspace: String,
    pub conflicting_workspace: String,
}

/// Scans `rules` for `wm_class`es that are assigned to more than one
/// workspace and reports every such pair, in the order encountered.
///
/// A row is skipped entirely — it can neither conflict nor be conflicted
/// with — when `workspace` is `"default"` (no override set) or `wm_class`
/// is empty (nothing to match against). This mirrors the Python
/// original's `if ws == "default" or not wm: continue`.
///
/// `&[(&str, &str)]` rather than owned `String`s: this function only ever
/// reads the pairs, so the caller keeps ownership and we avoid cloning
/// data that already lives in the UI layer or in a Python string.
pub fn find_conflicts(rules: &[(&str, &str)]) -> Vec<Conflict> {
    let mut seen: HashMap<&str, &str> = HashMap::new();
    let mut conflicts = Vec::new();

    for &(wm_class, workspace) in rules {
        if workspace == "default" || wm_class.is_empty() {
            continue;
        }

        if let Some(&first_workspace) = seen.get(wm_class)
            && first_workspace != workspace
        {
            conflicts.push(Conflict {
                wm_class: wm_class.to_string(),
                first_workspace: first_workspace.to_string(),
                conflicting_workspace: workspace.to_string(),
            });
        }

        // Unconditional, on every non-skipped row — *not* only the first
        // time we see this `wm_class`. In the Python original,
        // `seen[wm] = ws` sits one indentation level outside the
        // preceding `if`, so it re-runs every iteration regardless of
        // whether a conflict was just recorded. Concretely: a third
        // occurrence of the same `wm_class` with yet another workspace is
        // compared against the *second* workspace, not the first one.
        // That's a faithful port, not a chosen design — see the
        // `third_occurrence_compares_against_most_recent_workspace` test.
        seen.insert(wm_class, workspace);
    }

    conflicts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_conflict_for_single_rule() {
        let rules = [("kitty", "1")];
        assert!(find_conflicts(&rules).is_empty());
    }

    #[test]
    fn rows_with_default_workspace_are_ignored() {
        let rules = [("kitty", "default"), ("kitty", "1")];
        // Only one real assignment ever gets recorded, so there is
        // nothing for it to conflict with.
        assert!(find_conflicts(&rules).is_empty());
    }

    #[test]
    fn rows_with_empty_wm_class_are_ignored() {
        let rules = [("", "1"), ("", "2")];
        assert!(find_conflicts(&rules).is_empty());
    }

    #[test]
    fn same_workspace_repeated_is_not_a_conflict() {
        let rules = [("kitty", "1"), ("kitty", "1"), ("kitty", "1")];
        assert!(find_conflicts(&rules).is_empty());
    }

    #[test]
    fn detects_conflict_between_two_different_workspaces() {
        let rules = [("kitty", "1"), ("kitty", "2")];
        let conflicts = find_conflicts(&rules);
        assert_eq!(
            conflicts,
            vec![Conflict {
                wm_class: "kitty".to_string(),
                first_workspace: "1".to_string(),
                conflicting_workspace: "2".to_string(),
            }]
        );
    }

    #[test]
    fn third_occurrence_compares_against_most_recent_workspace() {
        // Edge case: `seen[wm]` is overwritten after *every* comparison,
        // not just the first. So workspace "3" is compared against "2"
        // (the most recently seen value), producing a second conflict —
        // not compared against "1" (the original), which would report
        // only one.
        let rules = [("kitty", "1"), ("kitty", "2"), ("kitty", "3")];
        let conflicts = find_conflicts(&rules);

        assert_eq!(conflicts.len(), 2);
        assert_eq!(conflicts[0].first_workspace, "1");
        assert_eq!(conflicts[0].conflicting_workspace, "2");
        assert_eq!(conflicts[1].first_workspace, "2");
        assert_eq!(conflicts[1].conflicting_workspace, "3");
    }

    #[test]
    fn unrelated_wm_classes_do_not_interfere() {
        let rules = [
            ("kitty", "1"),
            ("firefox", "2"),
            ("kitty", "1"),
            ("firefox", "3"),
        ];
        let conflicts = find_conflicts(&rules);
        assert_eq!(conflicts.len(), 1);
        assert_eq!(conflicts[0].wm_class, "firefox");
    }

    #[test]
    fn no_rules_means_no_conflicts() {
        assert!(find_conflicts(&[]).is_empty());
    }
}
