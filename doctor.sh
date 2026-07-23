#!/bin/bash
#
# Caelestia Settings — Hyprland integration doctor
#
# Checks (and repairs) the handful of hyprland.conf lines the app depends
# on: the Super+I keybind, the rules.conf/monitors.conf `source` lines, and
# the Polkit auth agent autostart. This is the exact same check-then-append
# logic install.sh's "STEP 6: Configuring Hyprland" already runs on every
# install — pulled out here so it can be re-run standalone (e.g. after a
# manual hyprland.conf edit knocked one of these lines out) without a full
# reinstall or git clone, and so install.sh doesn't have to keep two copies
# of the same checks in sync.
#
# Purely additive/idempotent: a missing line is appended, an existing one
# is left alone. Nothing is ever deleted or rewritten, so there is nothing
# here that needs a backup.

set -e

HYPR_CONFIG_DIR="$HOME/.config/hypr"
HYPR_CONFIG_FILE="$HYPR_CONFIG_DIR/hyprland.conf"
HYPR_INCLUDES_DIR="$HYPR_CONFIG_DIR/hyprland"
RULES_CONFIG_FILE="$HYPR_INCLUDES_DIR/rules.conf"
MONITOR_CONFIG_FILE="$HYPR_INCLUDES_DIR/monitors.conf"

# Collects "<status>: <label>" strings for the closing summary. Global
# (not local) on purpose: run_hyprland_doctor() is the only place this is
# read back, but keeping it a plain script-level array is simpler than
# threading a return value through check_and_add()'s call sites.
_DOCTOR_RESULTS=()

# check_and_add NEEDLE CONTENT LABEL
#
# Appends CONTENT (verbatim, may be multi-line) to $HYPR_CONFIG_FILE unless
# NEEDLE is already found in it (grep -F, literal match — these lines can
# contain characters like '.' that would otherwise be regex metacharacters).
check_and_add() {
    local needle="$1"
    local content="$2"
    local label="$3"

    if grep -q -F "$needle" "$HYPR_CONFIG_FILE"; then
        _DOCTOR_RESULTS+=("OK:    $label")
    else
        echo "   ...Adding: $label"
        printf '%s\n' "$content" >> "$HYPR_CONFIG_FILE"
        _DOCTOR_RESULTS+=("FIXED: $label (was missing, now added)")
    fi
}

run_hyprland_doctor() {
    echo ">>> Checking Hyprland integration..."

    mkdir -p "$HYPR_CONFIG_DIR"
    mkdir -p "$HYPR_INCLUDES_DIR"
    touch "$HYPR_CONFIG_FILE"
    touch "$RULES_CONFIG_FILE"
    touch "$MONITOR_CONFIG_FILE"

    _DOCTOR_RESULTS=()

    local rules_source="source = $RULES_CONFIG_FILE"
    check_and_add "$rules_source" "$rules_source" "rules.conf 'source' line"

    # Kept identical to install.sh's original output: a leading blank line
    # and a comment header precede the monitors.conf source line, but the
    # rules.conf one above does not get either — matching that asymmetry
    # exactly so re-running this on an existing install produces the same
    # bytes install.sh itself would have written.
    local monitor_source="source = $MONITOR_CONFIG_FILE"
    local monitor_block
    monitor_block=$(printf '\n# Caelestia Monitor Config\n%s' "$monitor_source")
    check_and_add "$monitor_source" "$monitor_block" "monitors.conf 'source' line"

    local bind_cmd="bind = SUPER, I, exec, caelestia-settings"
    check_and_add "$bind_cmd" "$bind_cmd" "Super+I keybind"

    local polkit_needle="/usr/lib/polkit-kde-authentication-agent-1"
    local polkit_cmd="exec-once = $polkit_needle"
    check_and_add "$polkit_needle" "$polkit_cmd" "Polkit auth agent autostart"

    echo
    echo ">>> Hyprland integration summary:"
    for result in "${_DOCTOR_RESULTS[@]}"; do
        echo "   $result"
    done
    echo
}

# Sourced by install.sh (which then calls run_hyprland_doctor itself), but
# also directly runnable on its own: `./doctor.sh` repairs a live config
# without going through install.sh or app_update.sh at all.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    run_hyprland_doctor
fi
