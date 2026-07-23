//! PWM percent ⇄ raw-value conversion for sysfs fan control.
//!
//! Everything else in `fans.py` (sysfs discovery under `/sys/class/hwmon`,
//! psutil/pynvml reads, sudo-gated writes via subprocess) is hardware I/O,
//! not portable pure logic, and stays in Python — same reasoning as the
//! nmcli/yay wrappers elsewhere in the app. This file only covers the one
//! calculation that exists in both directions: turning a raw 0..=255 PWM
//! duty-cycle value into a 0..=100 percentage the UI slider shows, and back.

/// Converts a raw PWM value (0..=255, as read from a `pwmN` sysfs file) to
/// a percentage (0..=100).
///
/// The Python original computes `round(int(pwm_raw) / 255 * 100)`. We get
/// the same nearest-integer result without going through floating point at
/// all: `floor(raw*100/255 + 0.5)` written as the integer expression
/// `(raw*200 + 255) / 510` avoids any float rounding-error edge cases.
/// (255 as a denominator means an exact `.5` tie is impossible for integer
/// `raw`, so which half-rounding rule Python's `round()` uses never
/// actually matters here — this only ever rounds a clean nearest value.)
pub fn pwm_raw_to_percent(raw: u8) -> u8 {
    let raw = raw as u32;
    let rounded = (raw * 200 + 255) / 510;
    rounded as u8 // raw ∈ 0..=255 bounds this to 0..=100, always fits.
}

/// Converts a percentage (meant to be 0..=100) back to a raw PWM value
/// (0..=255) for writing to a `pwmN` sysfs file.
///
/// The Python original computes `int(pct / 100 * 255)`, and Python's
/// `int()` truncates toward zero rather than rounding. That is a
/// deliberate asymmetry in the original we must keep, not "fix": reading
/// back a value this function just wrote will not always reproduce the
/// percentage `pwm_raw_to_percent` reported before the write (e.g. 50% ->
/// 127 here, but `pwm_raw_to_percent(127)` rounds back up to 50 — while
/// 51% written from that same UI would truncate to a different raw byte).
///
/// `percent` is only ever meant to carry 0..=100 (the slider's range), but
/// the type doesn't enforce that, so a value above 100 is clamped to 255
/// instead of overflowing past a valid PWM byte.
pub fn percent_to_pwm_raw(percent: u8) -> u8 {
    let raw = percent as u32 * 255 / 100;
    raw.min(255) as u8
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn raw_to_percent_at_the_extremes() {
        assert_eq!(pwm_raw_to_percent(0), 0);
        assert_eq!(pwm_raw_to_percent(255), 100);
    }

    #[test]
    fn raw_to_percent_rounds_to_nearest() {
        // 128 / 255 * 100 = 50.196... -> rounds down to 50.
        assert_eq!(pwm_raw_to_percent(128), 50);
        // 130 / 255 * 100 = 50.980... -> rounds up to 51.
        assert_eq!(pwm_raw_to_percent(130), 51);
    }

    #[test]
    fn percent_to_raw_at_the_extremes() {
        assert_eq!(percent_to_pwm_raw(0), 0);
        assert_eq!(percent_to_pwm_raw(100), 255);
    }

    #[test]
    fn percent_to_raw_truncates_instead_of_rounding() {
        // 50 / 100 * 255 = 127.5 -> Python's int() truncates to 127, not
        // 128, unlike the rounding used on the read path.
        assert_eq!(percent_to_pwm_raw(50), 127);
    }

    #[test]
    fn read_write_asymmetry_is_intentional() {
        // Writing 50% truncates to raw 127, but reading raw 127 back
        // rounds up to 50% again: the two directions are not exact
        // inverses of each other, by design (see doc comment above).
        let raw = percent_to_pwm_raw(50);
        assert_eq!(raw, 127);
        assert_eq!(pwm_raw_to_percent(raw), 50);
    }

    #[test]
    fn percent_above_100_clamps_instead_of_overflowing() {
        assert_eq!(percent_to_pwm_raw(200), 255);
        assert_eq!(percent_to_pwm_raw(u8::MAX), 255);
    }
}
