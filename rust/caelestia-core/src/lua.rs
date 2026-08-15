//! Minimal Lua codec for the app-controlled subset of Hyprland's Lua config
//! provider syntax: table constructors (`{ key = value, ... }`) and call
//! expressions of the shape `dotted.path(arg, arg, ...)` — the forms the app
//! itself reads and writes, e.g. `hl.monitor({ output = "DP-1", ... })`,
//! `hl.window_rule({ match = { class = "kitty" }, workspace = "2" })`.
//!
//! This is deliberately NOT a general Lua parser: it never evaluates
//! expressions, follows variables, or parses arbitrary statements (loops,
//! function bodies, local declarations, ...). Anything outside the
//! supported grammar returns a `LuaError` so callers can fall back to
//! treating that content as opaque/read-only instead of risking corruption
//! by guessing at its meaning.

use std::fmt;

// ---------------------------------------------------------------------
// Value model
// ---------------------------------------------------------------------

/// A parsed Lua value, restricted to the subset this codec understands.
///
/// `Number` keeps the original source text (not an `f64`) so that
/// `parse` -> `render` round-trips byte-for-byte for numbers like
/// `179.952` instead of risking float formatting drift.
#[derive(Debug, Clone, PartialEq)]
pub enum LuaValue {
    Nil,
    Bool(bool),
    Number(String),
    Str(String),
    /// Table entries in source order. `None` key = positional/array entry
    /// (`{ "a", "b" }`); `Some(key)` = `key = value` or `["key"] = value`.
    Table(Vec<(Option<String>, LuaValue)>),
}

/// `dotted.path(args...)`, e.g. `hl.monitor({ ... })` or
/// `hl.dsp.exec_cmd("foot")`.
#[derive(Debug, Clone, PartialEq)]
pub struct LuaCall {
    pub path: Vec<String>,
    pub args: Vec<LuaValue>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LuaError(pub String);

impl fmt::Display for LuaError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for LuaError {}

// ---------------------------------------------------------------------
// Tokenizer
// ---------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
enum Token {
    LBrace,
    RBrace,
    LBracket,
    RBracket,
    LParen,
    RParen,
    Comma,
    Eq,
    Dot,
    Ident(String),
    Str(String),
    Number(String),
    True,
    False,
    Nil,
}

struct Lexer<'a> {
    chars: std::iter::Peekable<std::str::CharIndices<'a>>,
    src: &'a str,
}

impl<'a> Lexer<'a> {
    fn new(src: &'a str) -> Self {
        Self {
            chars: src.char_indices().peekable(),
            src,
        }
    }

    fn tokenize(mut self) -> Result<Vec<Token>, LuaError> {
        let mut tokens = Vec::new();
        loop {
            self.skip_ws_and_comments()?;
            let Some(&(pos, c)) = self.chars.peek() else {
                break;
            };
            match c {
                '{' => {
                    self.chars.next();
                    tokens.push(Token::LBrace);
                }
                '}' => {
                    self.chars.next();
                    tokens.push(Token::RBrace);
                }
                '[' => {
                    self.chars.next();
                    tokens.push(Token::LBracket);
                }
                ']' => {
                    self.chars.next();
                    tokens.push(Token::RBracket);
                }
                '(' => {
                    self.chars.next();
                    tokens.push(Token::LParen);
                }
                ')' => {
                    self.chars.next();
                    tokens.push(Token::RParen);
                }
                ',' => {
                    self.chars.next();
                    tokens.push(Token::Comma);
                }
                '=' => {
                    self.chars.next();
                    tokens.push(Token::Eq);
                }
                '.' if !self.next_is_digit_after_dot() => {
                    self.chars.next();
                    tokens.push(Token::Dot);
                }
                '"' | '\'' => tokens.push(Token::Str(self.read_string(c)?)),
                c if c == '-' || c.is_ascii_digit() => {
                    tokens.push(Token::Number(self.read_number()?))
                }
                c if c.is_alphabetic() || c == '_' => {
                    let ident = self.read_ident();
                    tokens.push(match ident.as_str() {
                        "true" => Token::True,
                        "false" => Token::False,
                        "nil" => Token::Nil,
                        _ => Token::Ident(ident),
                    });
                }
                other => {
                    return Err(LuaError(format!(
                        "unexpected character {other:?} at byte {pos}"
                    )));
                }
            }
        }
        Ok(tokens)
    }

    fn next_is_digit_after_dot(&mut self) -> bool {
        // A bare '.' is only ever punctuation (`hl.monitor`) in the syntax
        // this codec supports — leading-dot numbers like `.5` never appear
        // in the target examples, so treat every '.' as Token::Dot.
        false
    }

    fn skip_ws_and_comments(&mut self) -> Result<(), LuaError> {
        loop {
            while let Some(&(_, c)) = self.chars.peek() {
                if c.is_whitespace() {
                    self.chars.next();
                } else {
                    break;
                }
            }
            if self.starts_with("--") {
                self.chars.next();
                self.chars.next();
                if self.starts_with("[[") {
                    self.chars.next();
                    self.chars.next();
                    self.consume_until("]]")?;
                } else {
                    while let Some(&(_, c)) = self.chars.peek() {
                        if c == '\n' {
                            break;
                        }
                        self.chars.next();
                    }
                }
                continue;
            }
            break;
        }
        Ok(())
    }

    fn starts_with(&mut self, pat: &str) -> bool {
        let Some(&(pos, _)) = self.chars.peek() else {
            return false;
        };
        self.src[pos..].starts_with(pat)
    }

    fn consume_until(&mut self, end: &str) -> Result<(), LuaError> {
        loop {
            if self.starts_with(end) {
                for _ in 0..end.chars().count() {
                    self.chars.next();
                }
                return Ok(());
            }
            if self.chars.next().is_none() {
                return Err(LuaError("unterminated block comment".into()));
            }
        }
    }

    fn read_string(&mut self, quote: char) -> Result<String, LuaError> {
        self.chars.next(); // opening quote
        let mut out = String::new();
        loop {
            match self.chars.next() {
                None => return Err(LuaError("unterminated string literal".into())),
                Some((_, c)) if c == quote => return Ok(out),
                Some((_, '\\')) => {
                    let Some((_, esc)) = self.chars.next() else {
                        return Err(LuaError("unterminated escape sequence".into()));
                    };
                    out.push(match esc {
                        'n' => '\n',
                        't' => '\t',
                        'r' => '\r',
                        '\\' => '\\',
                        '"' => '"',
                        '\'' => '\'',
                        other => {
                            return Err(LuaError(format!("unsupported escape sequence \\{other}")));
                        }
                    });
                }
                Some((_, c)) => out.push(c),
            }
        }
    }

    fn read_number(&mut self) -> Result<String, LuaError> {
        let mut out = String::new();
        if let Some(&(_, '-')) = self.chars.peek() {
            out.push('-');
            self.chars.next();
        }
        let mut saw_digit = false;
        while let Some(&(_, c)) = self.chars.peek() {
            if c.is_ascii_digit() {
                saw_digit = true;
                out.push(c);
                self.chars.next();
            } else {
                break;
            }
        }
        if let Some(&(_, '.')) = self.chars.peek() {
            out.push('.');
            self.chars.next();
            while let Some(&(_, c)) = self.chars.peek() {
                if c.is_ascii_digit() {
                    saw_digit = true;
                    out.push(c);
                    self.chars.next();
                } else {
                    break;
                }
            }
        }
        if !saw_digit {
            return Err(LuaError(format!("invalid number literal {out:?}")));
        }
        Ok(out)
    }

    fn read_ident(&mut self) -> String {
        let mut out = String::new();
        while let Some(&(_, c)) = self.chars.peek() {
            if c.is_alphanumeric() || c == '_' {
                out.push(c);
                self.chars.next();
            } else {
                break;
            }
        }
        out
    }
}

// ---------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------

struct Parser {
    tokens: Vec<Token>,
    pos: usize,
}

impl Parser {
    fn peek(&self) -> Option<&Token> {
        self.tokens.get(self.pos)
    }

    fn advance(&mut self) -> Option<Token> {
        let t = self.tokens.get(self.pos).cloned();
        self.pos += 1;
        t
    }

    fn expect(&mut self, tok: &Token) -> Result<(), LuaError> {
        match self.advance() {
            Some(ref t) if t == tok => Ok(()),
            other => Err(LuaError(format!("expected {tok:?}, found {other:?}"))),
        }
    }

    fn parse_value(&mut self) -> Result<LuaValue, LuaError> {
        match self.advance() {
            Some(Token::Nil) => Ok(LuaValue::Nil),
            Some(Token::True) => Ok(LuaValue::Bool(true)),
            Some(Token::False) => Ok(LuaValue::Bool(false)),
            Some(Token::Number(n)) => Ok(LuaValue::Number(n)),
            Some(Token::Str(s)) => Ok(LuaValue::Str(s)),
            Some(Token::LBrace) => self.parse_table_body(),
            other => Err(LuaError(format!("expected a value, found {other:?}"))),
        }
    }

    fn parse_table_body(&mut self) -> Result<LuaValue, LuaError> {
        let mut entries = Vec::new();
        loop {
            if let Some(Token::RBrace) = self.peek() {
                self.advance();
                break;
            }
            let key = self.try_parse_key()?;
            let value = self.parse_value()?;
            entries.push((key, value));
            match self.peek() {
                Some(Token::Comma) => {
                    self.advance();
                }
                Some(Token::RBrace) => {
                    self.advance();
                    break;
                }
                other => return Err(LuaError(format!("expected ',' or '}}', found {other:?}"))),
            }
        }
        Ok(LuaValue::Table(entries))
    }

    /// Consumes `ident =` or `["str"] =` if present, leaving the cursor at
    /// the value; otherwise leaves the cursor untouched (positional entry).
    fn try_parse_key(&mut self) -> Result<Option<String>, LuaError> {
        match self.peek() {
            Some(Token::Ident(_)) => {
                if self.tokens.get(self.pos + 1) == Some(&Token::Eq) {
                    let Some(Token::Ident(name)) = self.advance() else {
                        unreachable!()
                    };
                    self.advance(); // '='
                    Ok(Some(name))
                } else {
                    Ok(None)
                }
            }
            Some(Token::LBracket) => {
                if self.tokens.get(self.pos + 2) == Some(&Token::RBracket)
                    && self.tokens.get(self.pos + 3) == Some(&Token::Eq)
                {
                    self.advance(); // '['
                    let Some(Token::Str(name)) = self.advance() else {
                        return Err(LuaError("expected string key inside [...]".into()));
                    };
                    self.advance(); // ']'
                    self.advance(); // '='
                    Ok(Some(name))
                } else {
                    Ok(None)
                }
            }
            _ => Ok(None),
        }
    }

    fn parse_call(&mut self) -> Result<LuaCall, LuaError> {
        let mut path = Vec::new();
        loop {
            match self.advance() {
                Some(Token::Ident(name)) => path.push(name),
                other => {
                    return Err(LuaError(format!(
                        "expected identifier in call path, found {other:?}"
                    )));
                }
            }
            match self.peek() {
                Some(Token::Dot) => {
                    self.advance();
                }
                _ => break,
            }
        }
        self.expect(&Token::LParen)?;
        let mut args = Vec::new();
        if self.peek() != Some(&Token::RParen) {
            loop {
                args.push(self.parse_value()?);
                match self.peek() {
                    Some(Token::Comma) => {
                        self.advance();
                    }
                    _ => break,
                }
            }
        }
        self.expect(&Token::RParen)?;
        Ok(LuaCall { path, args })
    }
}

/// Parses a single Lua value (typically a table literal) from `input`.
/// Trailing content after the value is rejected — this codec only ever
/// parses one complete, self-contained expression at a time.
pub fn parse_value(input: &str) -> Result<LuaValue, LuaError> {
    let tokens = Lexer::new(input).tokenize()?;
    let mut parser = Parser { tokens, pos: 0 };
    let value = parser.parse_value()?;
    if parser.pos != parser.tokens.len() {
        return Err(LuaError("unexpected trailing content after value".into()));
    }
    Ok(value)
}

/// Parses a single call expression, e.g. `hl.monitor({ output = "DP-1" })`.
pub fn parse_call(input: &str) -> Result<LuaCall, LuaError> {
    let tokens = Lexer::new(input).tokenize()?;
    let mut parser = Parser { tokens, pos: 0 };
    let call = parser.parse_call()?;
    if parser.pos != parser.tokens.len() {
        return Err(LuaError("unexpected trailing content after call".into()));
    }
    Ok(call)
}

// ---------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------

/// Escapes a Rust string as a double-quoted Lua string literal body
/// (without the surrounding quotes).
fn escape_lua_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            other => out.push(other),
        }
    }
    out
}

fn render_key(key: &str) -> String {
    let is_plain_ident = !key.is_empty()
        && key
            .chars()
            .next()
            .is_some_and(|c| c.is_alphabetic() || c == '_')
        && key.chars().all(|c| c.is_alphanumeric() || c == '_');
    if is_plain_ident {
        key.to_string()
    } else {
        format!("[\"{}\"]", escape_lua_string(key))
    }
}

/// Renders a `LuaValue` deterministically, single-line, matching the app's
/// target style: `{ key = "value", nested = { a = 1 } }`.
pub fn render_value(value: &LuaValue) -> String {
    match value {
        LuaValue::Nil => "nil".to_string(),
        LuaValue::Bool(b) => b.to_string(),
        LuaValue::Number(n) => n.clone(),
        LuaValue::Str(s) => format!("\"{}\"", escape_lua_string(s)),
        LuaValue::Table(entries) => {
            if entries.is_empty() {
                return "{}".to_string();
            }
            let body: Vec<String> = entries
                .iter()
                .map(|(key, val)| match key {
                    Some(k) => format!("{} = {}", render_key(k), render_value(val)),
                    None => render_value(val),
                })
                .collect();
            format!("{{ {} }}", body.join(", "))
        }
    }
}

/// Renders a full call expression, e.g. `render_call(&["hl", "monitor"], &[table])`
/// -> `hl.monitor({ ... })`.
pub fn render_call(path: &[&str], args: &[LuaValue]) -> String {
    let args_str: Vec<String> = args.iter().map(render_value).collect();
    format!("{}({})", path.join("."), args_str.join(", "))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn table(entries: Vec<(&str, LuaValue)>) -> LuaValue {
        LuaValue::Table(
            entries
                .into_iter()
                .map(|(k, v)| (Some(k.to_string()), v))
                .collect(),
        )
    }

    #[test]
    fn parses_flat_table() {
        let v = parse_value(r#"{ output = "DP-1", scale = 1.0, bitdepth = 10 }"#).unwrap();
        assert_eq!(
            v,
            table(vec![
                ("output", LuaValue::Str("DP-1".into())),
                ("scale", LuaValue::Number("1.0".into())),
                ("bitdepth", LuaValue::Number("10".into())),
            ])
        );
    }

    #[test]
    fn parses_nested_table() {
        let v = parse_value(r#"{ match = { class = "kitty" }, workspace = "2" }"#).unwrap();
        assert_eq!(
            v,
            table(vec![
                (
                    "match",
                    table(vec![("class", LuaValue::Str("kitty".into()))])
                ),
                ("workspace", LuaValue::Str("2".into())),
            ])
        );
    }

    #[test]
    fn parses_booleans_and_nil() {
        let v = parse_value(r#"{ default = true, persistent = false, extra = nil }"#).unwrap();
        assert_eq!(
            v,
            table(vec![
                ("default", LuaValue::Bool(true)),
                ("persistent", LuaValue::Bool(false)),
                ("extra", LuaValue::Nil),
            ])
        );
    }

    #[test]
    fn parses_negative_and_decimal_numbers() {
        let v = parse_value(r#"{ x = -1, y = -0.5, z = 179.952 }"#).unwrap();
        assert_eq!(
            v,
            table(vec![
                ("x", LuaValue::Number("-1".into())),
                ("y", LuaValue::Number("-0.5".into())),
                ("z", LuaValue::Number("179.952".into())),
            ])
        );
    }

    #[test]
    fn parses_bracketed_string_key() {
        let v = parse_value(r#"{ ["kb_layout"] = "de" }"#).unwrap();
        assert_eq!(v, table(vec![("kb_layout", LuaValue::Str("de".into()))]));
    }

    #[test]
    fn parses_positional_array_entries() {
        let v = parse_value(r#"{ "a", "b", "c" }"#).unwrap();
        assert_eq!(
            v,
            LuaValue::Table(vec![
                (None, LuaValue::Str("a".into())),
                (None, LuaValue::Str("b".into())),
                (None, LuaValue::Str("c".into())),
            ])
        );
    }

    #[test]
    fn parses_trailing_comma() {
        let v = parse_value("{ a = 1, b = 2, }").unwrap();
        assert_eq!(
            v,
            table(vec![
                ("a", LuaValue::Number("1".into())),
                ("b", LuaValue::Number("2".into()))
            ])
        );
    }

    #[test]
    fn parses_empty_table() {
        assert_eq!(parse_value("{}").unwrap(), LuaValue::Table(vec![]));
        assert_eq!(parse_value("{ }").unwrap(), LuaValue::Table(vec![]));
    }

    #[test]
    fn skips_line_and_block_comments() {
        let v =
            parse_value("{ -- a line comment\n  a = 1, --[[ a block\n comment ]] b = 2 }").unwrap();
        assert_eq!(
            v,
            table(vec![
                ("a", LuaValue::Number("1".into())),
                ("b", LuaValue::Number("2".into()))
            ])
        );
    }

    #[test]
    fn handles_string_escapes_roundtrip() {
        let v = parse_value(r#"{ s = "line1\nline2\t\"quoted\"\\end" }"#).unwrap();
        assert_eq!(
            v,
            table(vec![(
                "s",
                LuaValue::Str("line1\nline2\t\"quoted\"\\end".into())
            )])
        );
        let LuaValue::Table(entries) = &v else {
            unreachable!()
        };
        assert_eq!(
            render_value(&entries[0].1),
            r#""line1\nline2\t\"quoted\"\\end""#
        );
    }

    #[test]
    fn handles_unicode_strings() {
        let src = r#"{ label = "Bürö – 日本語 – emoji ✨" }"#;
        let v = parse_value(src).unwrap();
        assert_eq!(
            v,
            table(vec![(
                "label",
                LuaValue::Str("Bürö – 日本語 – emoji ✨".into())
            )])
        );
        let rendered = render_value(&v);
        assert_eq!(parse_value(&rendered).unwrap(), v);
    }

    #[test]
    fn empty_input_is_an_error() {
        assert!(parse_value("").is_err());
        assert!(parse_call("").is_err());
    }

    #[test]
    fn malformed_input_is_an_error() {
        assert!(parse_value("{ a = }").is_err());
        assert!(parse_value("{ a = 1").is_err()); // unterminated
        assert!(parse_value("not-a-value !!!").is_err());
        assert!(parse_value(r#"{ "unterminated }"#).is_err());
        assert!(parse_value("{ a = 1 b = 2 }").is_err()); // missing comma
    }

    #[test]
    fn unknown_escape_is_rejected() {
        assert!(parse_value(r#"{ s = "bad \q escape" }"#).is_err());
    }

    #[test]
    fn parses_call_with_table_arg() {
        let call = parse_call(
            r#"hl.monitor({ output = "DP-1", mode = "2560x1440@179.952", position = "0x0", scale = 1.0, bitdepth = 10 })"#,
        )
        .unwrap();
        assert_eq!(call.path, vec!["hl", "monitor"]);
        assert_eq!(call.args.len(), 1);
    }

    #[test]
    fn parses_call_with_multiple_positional_args() {
        let call = parse_call(r#"hl.dsp.exec_cmd("foot")"#).unwrap();
        assert_eq!(call.path, vec!["hl", "dsp", "exec_cmd"]);
        assert_eq!(call.args, vec![LuaValue::Str("foot".into())]);
    }

    #[test]
    fn parses_call_with_no_args() {
        let call = parse_call("hl.reload()").unwrap();
        assert_eq!(call.path, vec!["hl", "reload"]);
        assert!(call.args.is_empty());
    }

    // ── Golden rendering tests, matching the app's target Lua style ──────

    #[test]
    fn renders_monitor_call_golden() {
        let table = table(vec![
            ("output", LuaValue::Str("DP-1".into())),
            ("mode", LuaValue::Str("2560x1440@179.952".into())),
            ("position", LuaValue::Str("0x0".into())),
            ("scale", LuaValue::Number("1.0".into())),
            ("bitdepth", LuaValue::Number("10".into())),
        ]);
        let rendered = render_call(&["hl", "monitor"], &[table]);
        assert_eq!(
            rendered,
            r#"hl.monitor({ output = "DP-1", mode = "2560x1440@179.952", position = "0x0", scale = 1.0, bitdepth = 10 })"#
        );
    }

    #[test]
    fn renders_workspace_rule_call_golden() {
        let table = table(vec![
            ("workspace", LuaValue::Str("1".into())),
            ("monitor", LuaValue::Str("DP-1".into())),
            ("default", LuaValue::Bool(true)),
            ("persistent", LuaValue::Bool(true)),
        ]);
        let rendered = render_call(&["hl", "workspace_rule"], &[table]);
        assert_eq!(
            rendered,
            r#"hl.workspace_rule({ workspace = "1", monitor = "DP-1", default = true, persistent = true })"#
        );
    }

    #[test]
    fn renders_window_rule_call_golden() {
        let table = table(vec![
            (
                "match",
                table(vec![("class", LuaValue::Str("kitty".into()))]),
            ),
            ("workspace", LuaValue::Str("2".into())),
        ]);
        let rendered = render_call(&["hl", "window_rule"], &[table]);
        assert_eq!(
            rendered,
            r#"hl.window_rule({ match = { class = "kitty" }, workspace = "2" })"#
        );
    }

    #[test]
    fn renders_bracketed_key_for_non_identifier_key() {
        let v = table(vec![("kb-layout!", LuaValue::Str("de".into()))]);
        assert_eq!(render_value(&v), r#"{ ["kb-layout!"] = "de" }"#);
    }

    #[test]
    fn roundtrips_parse_then_render_then_parse() {
        let sources = [
            r#"{ output = "DP-1", mode = "2560x1440@179.952", position = "0x0", scale = 1.0, bitdepth = 10 }"#,
            r#"{ match = { class = "kitty" }, workspace = "2" }"#,
            r#"{ kb_layout = "de", numlock_by_default = false }"#,
            "{}",
        ];
        for src in sources {
            let v1 = parse_value(src).unwrap();
            let rendered = render_value(&v1);
            let v2 = parse_value(&rendered).unwrap();
            assert_eq!(v1, v2, "roundtrip mismatch for {src:?}");
        }
    }
}
