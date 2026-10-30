use std::fmt;

/// A refusal: the input broke a rule. It names the field and the rule, and the
/// store is left unchanged. The CLI exits 1 on it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refusal {
    pub rule: &'static str,
    pub field: String,
    pub message: String,
}

impl Refusal {
    pub fn new(rule: &'static str, field: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            rule,
            field: field.into(),
            message: message.into(),
        }
    }
}

impl fmt::Display for Refusal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "refused {}: {}: {}", self.rule, self.field, self.message)
    }
}

#[derive(Debug)]
pub enum Error {
    /// A rule was broken (exit 1).
    Refused(Refusal),
    /// A usage, config, file or store error (exit 2).
    Other(String),
}

impl Error {
    pub fn other(msg: impl Into<String>) -> Self {
        Error::Other(msg.into())
    }
    pub fn exit_code(&self) -> i32 {
        match self {
            Error::Refused(_) => 1,
            Error::Other(_) => 2,
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Refused(r) => r.fmt(f),
            Error::Other(m) => f.write_str(m),
        }
    }
}

impl std::error::Error for Error {}

impl From<Refusal> for Error {
    fn from(r: Refusal) -> Self {
        Error::Refused(r)
    }
}

impl From<mysql::Error> for Error {
    fn from(e: mysql::Error) -> Self {
        Error::Other(format!("store error: {e}"))
    }
}

pub type Result<T> = std::result::Result<T, Error>;
