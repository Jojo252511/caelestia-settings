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
    /// Lenient-mode only: one character of Lua syntax this codec doesn't
    /// understand (operators, `local`/`function`/`end`, string
    /// concatenation, ...). Never produced in strict mode — there it's a
    /// hard `LuaError` instead. Carries no data because [`find_calls`]
    /// only needs to know call-boundary structure (parens/braces), not
    /// what this filler actually was.
    Other,
}

struct Lexer<'a> {
    chars: std::iter::Peekable<std::str::CharIndices<'a>>,
    src: &'a str,
    /// Strict (the default, used by `parse_value`/`parse_call` on an
    /// already-isolated fragment): any unrecognized syntax is a hard
    /// error. Lenient (used by `find_calls` to scan a whole file that may
    /// contain arbitrary Lua around the calls we care about): unrecognized
    /// syntax becomes `Token::Other` and scanning continues.
    strict: bool,
}

impl<'a> Lexer<'a> {
    fn new(src: &'a str) -> Self {
        Self {
            chars: src.char_indices().peekable(),
            src,
            strict: true,
        }
    }

    fn new_lenient(src: &'a str) -> Self {
        Self {
            chars: src.char_indices().peekable(),
            src,
            strict: false,
        }
    }

    /// Same tokenization as `tokenize`, but keeps each token's byte span
    /// so callers can slice the original source (needed by `find_calls`
    /// to recover exact call text, including multi-line tables).
    fn tokenize_spanned(mut self) -> Result<Vec<(Token, usize, usize)>, LuaError> {
        let mut tokens = Vec::new();
        loop {
            if let Err(e) = self.skip_ws_and_comments() {
                if self.strict {
                    return Err(e);
                }
                // Lenient: e.g. an unterminated `--[[` block comment later
                // in the file. Stop scanning rather than discarding every
                // valid token already found before it.
                break;
            }
            let Some(&(start, c)) = self.chars.peek() else {
                break;
            };
            let token = match c {
                '{' => {
                    self.chars.next();
                    Some(Token::LBrace)
                }
                '}' => {
                    self.chars.next();
                    Some(Token::RBrace)
                }
                '[' => {
                    self.chars.next();
                    Some(Token::LBracket)
                }
                ']' => {
                    self.chars.next();
                    Some(Token::RBracket)
                }
                '(' => {
                    self.chars.next();
                    Some(Token::LParen)
                }
                ')' => {
                    self.chars.next();
                    Some(Token::RParen)
                }
                ',' => {
                    self.chars.next();
                    Some(Token::Comma)
                }
                '=' => {
                    self.chars.next();
                    Some(Token::Eq)
                }
                '.' => {
                    self.chars.next();
                    Some(Token::Dot)
                }
                '"' | '\'' => match self.read_string(c) {
                    Ok(s) => Some(Token::Str(s)),
                    Err(e) => {
                        if self.strict {
                            return Err(e);
                        }
                        // Lenient: an unterminated string later in the file
                        // must not swallow the rest of the scan as "inside
                        // a string" — treat just the opening quote as
                        // filler and keep going from the next character.
                        Some(Token::Other)
                    }
                },
                c if c.is_ascii_digit() || (c == '-' && self.peek_next_is_digit()) => {
                    match self.read_number() {
                        Ok(n) => Some(Token::Number(n)),
                        Err(e) => {
                            if self.strict {
                                return Err(e);
                            }
                            self.chars.next();
                            Some(Token::Other)
                        }
                    }
                }
                c if c.is_alphabetic() || c == '_' => {
                    let ident = self.read_ident();
                    Some(match ident.as_str() {
                        "true" => Token::True,
                        "false" => Token::False,
                        "nil" => Token::Nil,
                        _ => Token::Ident(ident),
                    })
                }
                _ => {
                    if self.strict {
                        return Err(LuaError(format!(
                            "unexpected character {c:?} at byte {start}"
                        )));
                    }
                    self.chars.next();
                    Some(Token::Other)
                }
            };
            if let Some(tok) = token {
                let end = self.chars.peek().map(|&(p, _)| p).unwrap_or(self.src.len());
                tokens.push((tok, start, end));
            }
        }
        Ok(tokens)
    }

    fn tokenize(self) -> Result<Vec<Token>, LuaError> {
        Ok(self
            .tokenize_spanned()?
            .into_iter()
            .map(|(t, _, _)| t)
            .collect())
    }

    /// Looks past a `-` (without consuming it) to decide whether it starts
    /// a negative number literal or is standalone syntax (subtraction,
    /// concatenation-adjacent, ...). `Peekable` only gives one token of
    /// lookahead, so a cheap clone of the (index-based) iterator stands in
    /// for a second one.
    fn peek_next_is_digit(&self) -> bool {
        let mut ahead = self.chars.clone();
        ahead.next();
        matches!(ahead.peek(), Some((_, c)) if c.is_ascii_digit())
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

    /// Consumes exactly `Token::Ident(name)`, or fails — used by the
    /// strict autostart-shape parser, which (unlike `parse_call`'s
    /// generic dotted-path loop) expects specific keywords/identifiers
    /// at specific positions.
    fn expect_ident(&mut self, name: &str) -> Result<(), LuaError> {
        match self.advance() {
            Some(Token::Ident(ref found)) if found == name => Ok(()),
            other => Err(LuaError(format!(
                "expected identifier {name:?}, found {other:?}"
            ))),
        }
    }

    /// Consumes exactly `Token::Str(_)` and returns its contents, or fails.
    fn expect_str(&mut self) -> Result<String, LuaError> {
        match self.advance() {
            Some(Token::Str(s)) => Ok(s),
            other => Err(LuaError(format!(
                "expected a string literal, found {other:?}"
            ))),
        }
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

/// Finds every occurrence of a call to the dotted path `func_name` (e.g.
/// `"hl.window_rule"`) anywhere in `input`, tolerating arbitrary
/// surrounding Lua this codec doesn't understand — loops, `local`
/// declarations, string concatenation, other function calls, comments,
/// unrelated identifiers that merely happen to contain the same
/// substrings, and so on. None of that aborts the scan; unrecognized
/// syntax is simply inert filler.
///
/// Returns each match's byte span `(start, end)` — covering the full
/// `name(...)` text, including a nested table that spans multiple lines —
/// together with that exact source slice. This performs NO semantic
/// validation of the call itself: feed each returned text into
/// [`parse_call`] to get a structured result, and treat a `parse_call`
/// error on one match as "this particular call is unsupported", never as
/// a reason to discard the others or abort the caller's load.
///
/// A call whose parentheses are never closed (truncated/malformed input)
/// is simply not reported.
pub fn find_calls<'a>(input: &'a str, func_name: &str) -> Vec<(usize, usize, &'a str)> {
    let path: Vec<&str> = func_name.split('.').filter(|s| !s.is_empty()).collect();
    if path.is_empty() {
        return Vec::new();
    }
    let tokens = match Lexer::new_lenient(input).tokenize_spanned() {
        Ok(t) => t,
        Err(_) => return Vec::new(),
    };

    let mut spans = Vec::new();
    let mut i = 0usize;
    while i < tokens.len() {
        if let Some((start, end, next_i)) = match_call_at(&tokens, i, &path) {
            spans.push((start, end, &input[start..end]));
            i = next_i;
        } else {
            i += 1;
        }
    }
    spans
}

/// Attempts to match `path` (e.g. `["hl", "window_rule"]`) as a dotted
/// call starting exactly at token index `i`. On success returns the
/// call's `(start_byte, end_byte, index_of_first_token_after_call)`.
fn match_call_at(
    tokens: &[(Token, usize, usize)],
    i: usize,
    path: &[&str],
) -> Option<(usize, usize, usize)> {
    let mut j = i;
    for (k, seg) in path.iter().enumerate() {
        if k > 0 {
            match tokens.get(j)? {
                (Token::Dot, _, _) => j += 1,
                _ => return None,
            }
        }
        match tokens.get(j)? {
            (Token::Ident(name), _, _) if name == seg => j += 1,
            _ => return None,
        }
    }
    match tokens.get(j)? {
        (Token::LParen, _, _) => {}
        _ => return None,
    }

    let start = tokens[i].1;
    let mut depth = 0i32;
    let mut k = j;
    loop {
        match tokens.get(k)? {
            (Token::LParen, _, _) => {
                depth += 1;
                k += 1;
            }
            (Token::RParen, _, end) => {
                depth -= 1;
                let end = *end;
                k += 1;
                if depth == 0 {
                    return Some((start, end, k));
                }
            }
            _ => k += 1,
        }
    }
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

// ---------------------------------------------------------------------
// Autostart idiom: `hl.on("hyprland.start", function() ... end)`
// ---------------------------------------------------------------------
//
// Hyprland's Lua config has no flat `exec-once`-style call — autostart
// commands are registered by reacting to the `hyprland.start` event:
//
//   hl.on("hyprland.start", function()
//     hl.exec_cmd("waybar")
//   end)
//
// A `function() ... end` body is a Lua *statement sequence*, which this
// codec deliberately does not model as a general `LuaValue` (see the
// module doc comment: no loops, function bodies, or local declarations).
// The app's own autostart entries are always exactly this one fixed
// shape — one event registration, one `hl.exec_cmd` call, nothing else —
// so `parse_autostart_cmd` below is a dedicated STRICT parser for
// exactly that shape, not a lenient scan: unlike `find_calls`, it does
// NOT tolerate a different event name, extra statements in the handler
// body, or any other surrounding Lua. That strictness is deliberate and
// security-relevant — this parser is what decides whether a config
// entry is treated as "this app's own persisted value" for read-back and
// live-apply decisions, so it must never mistake a *different* event
// handler (e.g. `window.open`) or a handler with extra/altered
// statements for the app's own trusted `hyprland.start` entry.

/// Renders the app's single-command autostart idiom: an `hl.on(...)`
/// registration whose callback body is exactly one `hl.exec_cmd(cmd)`
/// call. `cmd` is a raw shell command string (the app is responsible for
/// its own shell-level quoting, e.g. `shlex.quote` on each argument,
/// before it ever reaches here) — this function only guarantees the
/// *Lua* string-literal escaping of that command. Rejects an empty or
/// whitespace-only `cmd`: an autostart entry with nothing to run is
/// meaningless and almost certainly a caller bug, not something that
/// should silently round-trip as a "valid" empty entry.
pub fn render_autostart_cmd(cmd: &str) -> Result<String, LuaError> {
    if cmd.trim().is_empty() {
        return Err(LuaError(
            "autostart command must not be empty or whitespace-only".into(),
        ));
    }
    Ok(format!(
        "hl.on(\"hyprland.start\", function() {} end)",
        render_call(&["hl", "exec_cmd"], &[LuaValue::Str(cmd.to_string())])
    ))
}

/// Strictly parses a single autostart entry, accepting ONLY the exact
/// shape rendered by [`render_autostart_cmd`]:
///
///   hl.on("hyprland.start", function() hl.exec_cmd("<cmd>") end)
///
/// Every token in `input` must match this shape in order — a different
/// event name, a different handler body (extra statements, a different
/// call, no call at all), trailing/leading content, or any syntax this
/// codec's strict lexer doesn't recognize anywhere in `input` is a hard
/// `LuaError`. This deliberately does NOT tolerate unrelated surrounding
/// Lua the way `find_calls` does: callers use this to decide whether a
/// config entry IS the app's own managed value, so a lookalike wrapping
/// a different event, or extra statements smuggled into the handler
/// body, must fail closed rather than be silently accepted. Also rejects
/// an empty/whitespace-only command, mirroring `render_autostart_cmd`.
pub fn parse_autostart_cmd(input: &str) -> Result<String, LuaError> {
    let tokens = Lexer::new(input).tokenize()?;
    let mut p = Parser { tokens, pos: 0 };

    p.expect_ident("hl")?;
    p.expect(&Token::Dot)?;
    p.expect_ident("on")?;
    p.expect(&Token::LParen)?;
    let event = p.expect_str()?;
    if event != "hyprland.start" {
        return Err(LuaError(format!(
            "expected the \"hyprland.start\" autostart event, found {event:?}"
        )));
    }
    p.expect(&Token::Comma)?;
    p.expect_ident("function")?;
    p.expect(&Token::LParen)?;
    p.expect(&Token::RParen)?;
    p.expect_ident("hl")?;
    p.expect(&Token::Dot)?;
    p.expect_ident("exec_cmd")?;
    p.expect(&Token::LParen)?;
    let cmd = p.expect_str()?;
    p.expect(&Token::RParen)?;
    p.expect_ident("end")?;
    p.expect(&Token::RParen)?;

    if p.pos != p.tokens.len() {
        return Err(LuaError(
            "unexpected trailing content after autostart entry".into(),
        ));
    }
    if cmd.trim().is_empty() {
        return Err(LuaError(
            "autostart command must not be empty or whitespace-only".into(),
        ));
    }
    Ok(cmd)
}

// ---------------------------------------------------------------------
// Primary-monitor xrandr command: strict validation
// ---------------------------------------------------------------------
//
// Not a Lua construct — this validates a plain shell command string
// (the payload of an `hl.exec_cmd(...)` / legacy `exec-once = ...`
// entry) — but it lives here, next to the autostart-cmd validation it's
// always paired with, and uses a small POSIX-subset shell tokenizer
// rather than a substring/heuristic check, per the same "fail closed on
// anything not exactly the app's own shape" principle as
// `parse_autostart_cmd` above.

/// Splits `s` into shell words, honoring single quotes (literal
/// contents, no escapes), double quotes (backslash escapes `\`, `"`,
/// `$`, `` ` ``), and backslash escapes outside quotes — the POSIX
/// subset Python's `shlex.split(s, posix=True)` implements. Returns
/// `Err` on an unterminated quote or a trailing backslash, exactly like
/// `shlex.split` raises `ValueError` in those cases.
fn shell_split(s: &str) -> Result<Vec<String>, LuaError> {
    let mut words = Vec::new();
    let mut current = String::new();
    let mut in_word = false;
    let mut chars = s.chars();
    while let Some(c) = chars.next() {
        match c {
            c if c.is_whitespace() => {
                if in_word {
                    words.push(std::mem::take(&mut current));
                    in_word = false;
                }
            }
            '\'' => {
                in_word = true;
                loop {
                    match chars.next() {
                        Some('\'') => break,
                        Some(c) => current.push(c),
                        None => return Err(LuaError("unterminated single quote".into())),
                    }
                }
            }
            '"' => {
                in_word = true;
                loop {
                    match chars.next() {
                        Some('"') => break,
                        Some('\\') => match chars.next() {
                            Some(c @ ('\\' | '"' | '$' | '`')) => current.push(c),
                            Some(c) => {
                                current.push('\\');
                                current.push(c);
                            }
                            None => {
                                return Err(LuaError("unterminated escape in double quote".into()));
                            }
                        },
                        Some(c) => current.push(c),
                        None => return Err(LuaError("unterminated double quote".into())),
                    }
                }
            }
            '\\' => {
                in_word = true;
                match chars.next() {
                    Some(c) => current.push(c),
                    None => return Err(LuaError("trailing backslash".into())),
                }
            }
            c => {
                in_word = true;
                current.push(c);
            }
        }
    }
    if in_word {
        words.push(current);
    }
    Ok(words)
}

/// Shell-quotes `s` the way `shlex.quote` does: bare when it contains
/// only characters that never need quoting, single-quoted (with `'`
/// escaped as `'\''`) otherwise.
fn shell_quote(s: &str) -> String {
    let safe = !s.is_empty()
        && s.chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '/'));
    if safe {
        s.to_string()
    } else {
        format!("'{}'", s.replace('\'', r"'\''"))
    }
}

/// Renders the app's own primary-monitor xrandr command deterministically
/// from a validated, non-empty monitor `name`, shell-quoting it. Rejects
/// an empty/whitespace-only name.
pub fn render_xrandr_primary_cmd(name: &str) -> Result<String, LuaError> {
    if name.trim().is_empty() {
        return Err(LuaError("monitor name must not be empty".into()));
    }
    Ok(format!("xrandr --output {} --primary", shell_quote(name)))
}

/// Strictly validates that `cmd` is EXACTLY the app's own primary-monitor
/// command — the four-token sequence `xrandr --output <name> --primary`
/// and nothing else: no extra/missing/reordered/duplicated options, no
/// additional shell commands or operators (shell_split only tokenizes
/// quoting, it never interprets `;`/`&&`/`|`, so e.g. `xrandr --output
/// DP-1 --primary; rm -rf ~` tokenizes to more than 4 words and is
/// rejected by the length match below), no empty name, and no other
/// program in place of `xrandr` (e.g. `echo --output DP-1 --primary`).
/// Returns the monitor name on success.
pub fn parse_xrandr_primary_cmd(cmd: &str) -> Result<String, LuaError> {
    let tokens = shell_split(cmd)?;
    match tokens.as_slice() {
        [prog, output_flag, name, primary_flag]
            if prog == "xrandr" && output_flag == "--output" && primary_flag == "--primary" =>
        {
            if name.trim().is_empty() {
                return Err(LuaError("monitor name must not be empty".into()));
            }
            Ok(name.clone())
        }
        _ => Err(LuaError(format!(
            "expected exactly \"xrandr --output <name> --primary\", found {cmd:?}"
        ))),
    }
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

    // ── find_calls ─────────────────────────────────────────────────────

    #[test]
    fn finds_single_line_call() {
        let src = r#"hl.window_rule({ match = { class = "kitty" }, workspace = "2" })"#;
        let spans = find_calls(src, "hl.window_rule");
        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0].2, src);
        assert_eq!(&src[spans[0].0..spans[0].1], src);
    }

    #[test]
    fn finds_multiline_call() {
        let src =
            "hl.window_rule({\n    match = { class = \"kitty\" },\n    workspace = \"2\",\n})";
        let spans = find_calls(src, "hl.window_rule");
        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0].2, src);
        let call = parse_call(spans[0].2).unwrap();
        assert_eq!(call.path, vec!["hl", "window_rule"]);
    }

    #[test]
    fn finds_multiple_calls_amid_unsupported_lua() {
        let src = r#"
local x = 1 + 2
-- a comment
hl.window_rule({ match = { class = "kitty" }, workspace = "2" })
if x > 1 then
    hl.exec_cmd("echo hi")
end
hl.window_rule({ match = { class = "firefox" }, float = true })
"#;
        let spans = find_calls(src, "hl.window_rule");
        assert_eq!(spans.len(), 2);
        assert!(spans[0].2.contains("kitty"));
        assert!(spans[1].2.contains("firefox"));
    }

    #[test]
    fn tolerates_string_concatenation_and_operators_elsewhere() {
        let src = r#"
local msg = "a" .. "b"
local y = 5 % 2
hl.window_rule({ match = { class = "kitty" }, workspace = "2" })
"#;
        let spans = find_calls(src, "hl.window_rule");
        assert_eq!(spans.len(), 1);
    }

    #[test]
    fn does_not_match_unrelated_identifier_containing_substring() {
        let src = r#"hl.window_rule_backup({ match = { class = "kitty" }, workspace = "2" })"#;
        assert!(find_calls(src, "hl.window_rule").is_empty());
    }

    #[test]
    fn does_not_match_shorter_prefix_path() {
        let src = r#"hl.window_rule.extra({ x = 1 })"#;
        // "hl.window_rule" must not spuriously match when followed by more
        // path segments instead of an opening paren.
        assert!(find_calls(src, "hl.window_rule").is_empty());
    }

    #[test]
    fn unterminated_call_is_not_reported() {
        let src = r#"hl.window_rule({ match = { class = "kitty" }, workspace = "2" }"#; // missing final )
        assert!(find_calls(src, "hl.window_rule").is_empty());
    }

    #[test]
    fn unterminated_string_elsewhere_does_not_abort_the_whole_scan() {
        let src = "hl.window_rule({ match = { class = \"kitty\" }, workspace = \"2\" })\nlocal bad = \"unterminated";
        let spans = find_calls(src, "hl.window_rule");
        assert_eq!(spans.len(), 1);
    }

    #[test]
    fn unterminated_block_comment_after_a_valid_call_keeps_that_call() {
        let src = "hl.window_rule({ match = { class = \"kitty\" }, workspace = \"2\" })\n--[[ never closed";
        let spans = find_calls(src, "hl.window_rule");
        assert_eq!(spans.len(), 1);
    }

    #[test]
    fn no_calls_returns_empty_not_error() {
        assert!(find_calls("local x = 1", "hl.window_rule").is_empty());
        assert!(find_calls("", "hl.window_rule").is_empty());
    }

    // ── autostart idiom ────────────────────────────────────────────────

    #[test]
    fn renders_autostart_cmd_golden() {
        let rendered = render_autostart_cmd("mpvpaper '*' /home/user/video.mp4").unwrap();
        assert_eq!(
            rendered,
            r#"hl.on("hyprland.start", function() hl.exec_cmd("mpvpaper '*' /home/user/video.mp4") end)"#
        );
    }

    #[test]
    fn autostart_cmd_roundtrips() {
        let cases = [
            "mpvpaper '*' /home/user/Videos/Wallpaper/clip.mp4 -o 'loop --no-audio --panscan=1.0'",
            "xrandr --output DP-1 --primary",
            r#"echo "quotes \"here\" and $(nope) and ; newline\nend""#,
            "path with spaces/and/'quotes'/and 日本語 ✨",
        ];
        for cmd in cases {
            let rendered = render_autostart_cmd(cmd).unwrap();
            let parsed = parse_autostart_cmd(&rendered).unwrap();
            assert_eq!(parsed, cmd, "roundtrip mismatch for {cmd:?}");
        }
    }

    #[test]
    fn autostart_cmd_parses_within_surrounding_whitespace_and_comments() {
        // A leading comment / trailing newline are just whitespace to the
        // strict lexer (comments are always skipped, in strict mode too)
        // — this is NOT the old lenient "tolerates arbitrary surrounding
        // Lua" behavior, which parse_autostart_cmd no longer has.
        let src =
            "-- autostart\nhl.on(\"hyprland.start\", function() hl.exec_cmd(\"waybar\") end)\n";
        assert_eq!(parse_autostart_cmd(src).unwrap(), "waybar");
    }

    #[test]
    fn autostart_cmd_rejects_empty_and_unrelated_input() {
        assert!(parse_autostart_cmd("").is_err());
        assert!(parse_autostart_cmd("local x = 1").is_err());
        assert!(parse_autostart_cmd("hl.exec_cmd(\"a\")").is_err());
    }

    #[test]
    fn autostart_cmd_rejects_empty_function_body() {
        assert!(parse_autostart_cmd("hl.on(\"hyprland.start\", function() end)").is_err());
    }

    #[test]
    fn autostart_cmd_rejects_multiple_statements_in_body() {
        let src = r#"hl.on("hyprland.start", function() hl.exec_cmd("a") hl.exec_cmd("b") end)"#;
        assert!(parse_autostart_cmd(src).is_err());
    }

    #[test]
    fn autostart_cmd_rejects_non_string_or_extra_arguments() {
        assert!(
            parse_autostart_cmd(r#"hl.on("hyprland.start", function() hl.exec_cmd(true) end)"#)
                .is_err()
        );
        assert!(
            parse_autostart_cmd(r#"hl.on("hyprland.start", function() hl.exec_cmd("a", "b") end)"#)
                .is_err()
        );
    }

    #[test]
    fn autostart_cmd_rejects_wrong_event_name() {
        let src = r#"hl.on("window.open", function() hl.exec_cmd("waybar") end)"#;
        assert!(parse_autostart_cmd(src).is_err());
    }

    #[test]
    fn autostart_cmd_rejects_wrong_handler_call() {
        // Same wrapper shape, but the statement inside isn't hl.exec_cmd.
        let src = r#"hl.on("hyprland.start", function() hl.other_call("x") end)"#;
        assert!(parse_autostart_cmd(src).is_err());
    }

    #[test]
    fn autostart_cmd_rejects_trailing_content_after_valid_entry() {
        let src = r#"hl.on("hyprland.start", function() hl.exec_cmd("a") end) hl.reload()"#;
        assert!(parse_autostart_cmd(src).is_err());
    }

    #[test]
    fn render_autostart_cmd_rejects_empty_or_whitespace_command() {
        assert!(render_autostart_cmd("").is_err());
        assert!(render_autostart_cmd("   ").is_err());
        assert!(render_autostart_cmd("\t\n").is_err());
    }

    #[test]
    fn parse_autostart_cmd_rejects_empty_or_whitespace_command_even_if_well_formed() {
        // A corrupted/hand-edited file could still contain this exact
        // shape with an empty string payload — reject it on the parse
        // side too, matching the render side's invariant.
        assert!(
            parse_autostart_cmd(r#"hl.on("hyprland.start", function() hl.exec_cmd("") end)"#)
                .is_err()
        );
        assert!(
            parse_autostart_cmd(r#"hl.on("hyprland.start", function() hl.exec_cmd("   ") end)"#)
                .is_err()
        );
    }

    // ── primary-monitor xrandr command ───────────────────────────────────

    #[test]
    fn shell_split_handles_quotes_and_escapes() {
        assert_eq!(shell_split("a b c").unwrap(), vec!["a", "b", "c"]);
        assert_eq!(
            shell_split("xrandr --output 'My Monitor' --primary").unwrap(),
            vec!["xrandr", "--output", "My Monitor", "--primary"]
        );
        assert_eq!(shell_split(r#"a "b c" d"#).unwrap(), vec!["a", "b c", "d"]);
        assert_eq!(shell_split(r"a\ b").unwrap(), vec!["a b"]);
    }

    #[test]
    fn shell_split_rejects_unterminated_quotes_and_trailing_backslash() {
        assert!(shell_split("a 'unterminated").is_err());
        assert!(shell_split("a \"unterminated").is_err());
        assert!(shell_split(r"a\").is_err());
    }

    #[test]
    fn shell_split_does_not_interpret_shell_operators() {
        // ';', '&&', '|' are just ordinary word characters to this
        // tokenizer — it never runs a shell, so it can't be tricked into
        // treating them as command separators; they simply become part
        // of (or extra) tokens, which callers like
        // parse_xrandr_primary_cmd then reject via the exact-length match.
        let tokens = shell_split("xrandr --output DP-1 --primary; rm -rf ~").unwrap();
        assert_eq!(
            tokens,
            vec!["xrandr", "--output", "DP-1", "--primary;", "rm", "-rf", "~"]
        );
    }

    #[test]
    fn render_xrandr_primary_cmd_golden() {
        assert_eq!(
            render_xrandr_primary_cmd("DP-1").unwrap(),
            "xrandr --output DP-1 --primary"
        );
    }

    #[test]
    fn render_xrandr_primary_cmd_quotes_dangerous_names() {
        let rendered = render_xrandr_primary_cmd("a b'c").unwrap();
        assert_eq!(shell_split(&rendered).unwrap()[2], "a b'c");
    }

    #[test]
    fn render_xrandr_primary_cmd_rejects_empty_name() {
        assert!(render_xrandr_primary_cmd("").is_err());
        assert!(render_xrandr_primary_cmd("   ").is_err());
    }

    #[test]
    fn xrandr_primary_cmd_roundtrips() {
        for name in ["DP-1", "HDMI-A-1", "a b'c", "日本語monitor"] {
            let rendered = render_xrandr_primary_cmd(name).unwrap();
            assert_eq!(parse_xrandr_primary_cmd(&rendered).unwrap(), name);
        }
    }

    #[test]
    fn parse_xrandr_primary_cmd_accepts_exact_shape_only() {
        assert_eq!(
            parse_xrandr_primary_cmd("xrandr --output DP-1 --primary").unwrap(),
            "DP-1"
        );
    }

    #[test]
    fn parse_xrandr_primary_cmd_rejects_wrong_program() {
        assert!(parse_xrandr_primary_cmd("echo --output DP-1 --primary").is_err());
    }

    #[test]
    fn parse_xrandr_primary_cmd_rejects_missing_primary_flag() {
        assert!(parse_xrandr_primary_cmd("xrandr --output DP-1").is_err());
    }

    #[test]
    fn parse_xrandr_primary_cmd_rejects_extra_or_reordered_tokens() {
        assert!(parse_xrandr_primary_cmd("xrandr --primary --output DP-1").is_err());
        assert!(parse_xrandr_primary_cmd("xrandr --output DP-1 --primary --auto").is_err());
        assert!(parse_xrandr_primary_cmd("xrandr --output DP-1 --primary --primary").is_err());
    }

    #[test]
    fn parse_xrandr_primary_cmd_rejects_multiple_commands_or_operators() {
        assert!(parse_xrandr_primary_cmd("xrandr --output DP-1 --primary; rm -rf ~").is_err());
        assert!(
            parse_xrandr_primary_cmd(
                "xrandr --output DP-1 --primary && xrandr --output DP-2 --primary"
            )
            .is_err()
        );
    }

    #[test]
    fn parse_xrandr_primary_cmd_rejects_empty_monitor_name() {
        assert!(parse_xrandr_primary_cmd("xrandr --output '' --primary").is_err());
    }

    #[test]
    fn parse_xrandr_primary_cmd_rejects_dynamic_or_unparseable_command() {
        assert!(parse_xrandr_primary_cmd("xrandr --output 'unterminated --primary").is_err());
    }

    #[test]
    fn each_matched_span_parses_as_a_valid_call() {
        let src = r#"
hl.window_rule({ match = { initial_title = "Spotify( Free)?" }, workspace = "special:music" })
"#;
        let spans = find_calls(src, "hl.window_rule");
        assert_eq!(spans.len(), 1);
        let call = parse_call(spans[0].2).unwrap();
        let LuaValue::Table(entries) = &call.args[0] else {
            panic!("expected table arg")
        };
        let match_table = entries
            .iter()
            .find(|(k, _)| k.as_deref() == Some("match"))
            .unwrap();
        assert_eq!(
            match_table.1,
            table(vec![(
                "initial_title",
                LuaValue::Str("Spotify( Free)?".into())
            )])
        );
    }
}
