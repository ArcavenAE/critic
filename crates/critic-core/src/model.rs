//! The run record as registered (design section 3) and its validation. Each
//! refusal names its rule: R-b void, R-c id shape, R-d enums, R-g paths, R-h
//! host names. R-a (duplicate id), R-e (lineage) and R-f (direct SQL) need the
//! store and live there.

use crate::config::Config;
use crate::error::Refusal;
use crate::paths::require_under;
use serde::Deserialize;
use serde_json::Value;

pub const KINDS: [&str; 4] = ["legion", "spike", "fork", "trial"];
pub const RUN_STATES: [&str; 7] = [
    "started",
    "completed",
    "stalled",
    "crashed",
    "timed-out",
    "limit-stopped",
    "void",
];
pub const STATUSES: [&str; 3] = ["active", "archived", "abandoned"];
pub const SPLITS: [&str; 3] = ["search", "validation", "test"];
pub const EDGE_KINDS: [&str; 2] = ["derived-from", "resumed-from"];
const HOST_KEYS: [&str; 3] = ["host", "hostname", "host_name"];

/// The seat stamp marvel will write at launch. Every field is optional: critic
/// never requires marvel, and never derives a stamp.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeatStamp {
    pub workspace: Option<String>,
    pub team: Option<String>,
    pub role: Option<String>,
    pub seat: Option<String>,
    pub cluster: Option<String>,
    pub prompt_hash: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionInput {
    pub harness: String,
    pub harness_session_id: String,
    pub marvel_session_key: Option<String>,
    #[serde(default)]
    pub stamp: Option<SeatStamp>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RunInput {
    pub id: String,
    pub kind: String,
    pub factory: Option<String>,
    pub factory_ref: Option<Value>,
    pub arm: Option<String>,
    pub run_id: Option<String>,
    pub block: Option<i64>,
    pub order: Option<i64>,
    pub protocol_role: Option<String>,
    pub split: Option<String>,
    pub parent: Option<String>,
    #[serde(default)]
    pub resumed_from: Vec<String>,
    pub protocol_sha: Option<String>,
    pub harness_build: Option<String>,
    pub locus: Option<Value>,
    #[serde(default)]
    pub sessions: Vec<SessionInput>,
    #[serde(default)]
    pub transcript_roots: Vec<String>,
    pub started_at: Option<String>,
    pub ended_at: Option<String>,
    pub status: Option<String>,
    pub run_state: Option<String>,
    pub void_rule: Option<String>,
    pub host_class: Option<String>,
    pub outcome: Option<Value>,
    /// A path under the runtime root; register stores it with its sha256.
    pub ledger: Option<String>,
    pub cost: Option<String>,
    pub metrics: Option<Value>,
    pub kos_finding: Option<String>,
}

/// A path and the sha256 of the file it names (P1).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FilePointer {
    pub path: String,
    pub sha256: String,
}

/// An input that passed every check that needs no store.
#[derive(Debug, Clone)]
pub struct ValidRun {
    pub input: RunInput,
    pub status: String,
}

/// R-h. A field named host, hostname or host_name, at any depth, is refused
/// before anything else reads the input: host names never enter the record.
pub fn reject_host_names(v: &Value) -> Result<(), Refusal> {
    fn walk(v: &Value, path: &str) -> Result<(), Refusal> {
        match v {
            Value::Object(m) => {
                for (k, child) in m {
                    let here = if path.is_empty() {
                        k.clone()
                    } else {
                        format!("{path}.{k}")
                    };
                    if HOST_KEYS.contains(&k.to_ascii_lowercase().as_str()) {
                        return Err(Refusal::new(
                            "R-h",
                            here,
                            "host names never enter the record; name the role of the host in host_class",
                        ));
                    }
                    walk(child, &here)?;
                }
                Ok(())
            }
            Value::Array(a) => {
                for (i, child) in a.iter().enumerate() {
                    walk(child, &format!("{path}[{i}]"))?;
                }
                Ok(())
            }
            _ => Ok(()),
        }
    }
    walk(v, "")
}

/// R-c. Lowercase, no slash, not empty. Anything else a shell or a path would
/// have to quote is refused too, so an id is safe wherever it is printed.
pub fn check_id(field: &str, id: &str) -> Result<(), Refusal> {
    let ok = !id.is_empty()
        && id.len() <= 128
        && id
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '-' | '_' | '.'));
    if ok {
        Ok(())
    } else {
        Err(Refusal::new(
            "R-c",
            field,
            format!("{id:?} is not an id: lowercase letters, digits, '-', '_' and '.', no '/', not empty"),
        ))
    }
}

pub fn check_enum(field: &str, value: &str, allowed: &[&str]) -> Result<(), Refusal> {
    if allowed.contains(&value) {
        Ok(())
    } else {
        Err(Refusal::new(
            "R-d",
            field,
            format!("{value:?} is not one of {}", allowed.join(", ")),
        ))
    }
}

/// R-b. A void always says which protocol rule voided it, and only a void does.
pub fn check_void(run_state: Option<&str>, void_rule: Option<&str>) -> Result<(), Refusal> {
    let rule = void_rule.map(str::trim).filter(|r| !r.is_empty());
    match (run_state, rule) {
        (Some("void"), None) => Err(Refusal::new(
            "R-b",
            "void_rule",
            "run_state void needs a void_rule naming the protocol rule",
        )),
        (Some("void"), Some(_)) => Ok(()),
        (_, Some(_)) => Err(Refusal::new(
            "R-b",
            "void_rule",
            "a void_rule is only valid with run_state void",
        )),
        (_, None) if void_rule.is_some() => Err(Refusal::new(
            "R-b",
            "void_rule",
            "a void_rule is only valid with run_state void",
        )),
        _ => Ok(()),
    }
}

/// Validate a run input against the config. Order: host names first (R-h), then
/// the id, the enums, the void pair, the host class and the runtime paths.
pub fn validate(input: RunInput, cfg: &Config) -> Result<ValidRun, Refusal> {
    check_id("id", &input.id)?;
    check_enum("kind", &input.kind, &KINDS)?;
    let status = input.status.clone().unwrap_or_else(|| "active".to_string());
    check_enum("status", &status, &STATUSES)?;
    if let Some(s) = &input.run_state {
        check_enum("run_state", s, &RUN_STATES)?;
    }
    if let Some(s) = &input.split {
        check_enum("split", s, &SPLITS)?;
    }
    check_void(input.run_state.as_deref(), input.void_rule.as_deref())?;
    if let Some(hc) = &input.host_class {
        if !cfg.host_classes.iter().any(|c| c == hc) {
            return Err(Refusal::new(
                "R-h",
                "host_class",
                format!(
                    "{hc:?} is not in the configured host_classes ({})",
                    cfg.host_classes.join(", ")
                ),
            ));
        }
    }
    if let Some(p) = &input.parent {
        check_id("parent", p)?;
    }
    for p in &input.resumed_from {
        check_id("resumed_from", p)?;
    }
    if let Ok(root) = cfg.runtime_root() {
        for (i, t) in input.transcript_roots.iter().enumerate() {
            require_under(root, &format!("transcript_roots[{i}]"), t)?;
        }
        for (f, p) in [("ledger", &input.ledger), ("cost", &input.cost)] {
            if let Some(p) = p {
                require_under(root, f, p)?;
            }
        }
    }
    Ok(ValidRun { input, status })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn host_names_are_refused_at_any_depth_and_in_any_case() {
        assert_eq!(
            reject_host_names(&json!({"id": "a", "host": "x"}))
                .unwrap_err()
                .rule,
            "R-h"
        );
        let deep = json!({"sessions": [{"stamp": {"Hostname": "x"}}]});
        let e = reject_host_names(&deep).unwrap_err();
        assert_eq!(e.field, "sessions[0].stamp.Hostname");
        assert!(
            reject_host_names(&json!({"host_class": "probe-host", "metrics": {"hosts": 3}}))
                .is_ok()
        );
    }

    #[test]
    fn ids_are_lowercase_without_slash_and_not_empty() {
        for bad in ["", "A", "a/b", "a b", "a;b"] {
            assert_eq!(check_id("id", bad).unwrap_err().rule, "R-c", "{bad:?}");
        }
        assert!(check_id("id", "trial-0a.1_x").is_ok());
    }

    #[test]
    fn void_and_its_rule_travel_together() {
        assert_eq!(check_void(Some("void"), None).unwrap_err().rule, "R-b");
        assert_eq!(
            check_void(Some("void"), Some("  ")).unwrap_err().rule,
            "R-b"
        );
        assert_eq!(
            check_void(Some("completed"), Some("s8.5"))
                .unwrap_err()
                .rule,
            "R-b"
        );
        assert_eq!(check_void(None, Some("s8.5")).unwrap_err().rule, "R-b");
        assert!(check_void(Some("void"), Some("s8.5")).is_ok());
        assert!(check_void(Some("completed"), None).is_ok());
        assert!(check_void(None, None).is_ok());
    }

    #[test]
    fn enums_are_closed() {
        assert_eq!(check_enum("kind", "nope", &KINDS).unwrap_err().rule, "R-d");
        assert!(check_enum("split", "validation", &SPLITS).is_ok());
    }
}
