//! The store: a trait the CLI talks to, and the Dolt (MySQL protocol) store
//! behind it. Dolt is the index of record (charter B3); the `critic` database
//! lives on the server the config points at, and nowhere else.

use crate::config::{Config, DoltUrl};
use crate::error::{Error, Refusal, Result};
use crate::graph;
use crate::model::{
    check_enum, check_void, FilePointer, ValidRun, EDGE_KINDS, RUN_STATES, STATUSES,
};
use mysql::prelude::Queryable;
use mysql::{Conn, OptsBuilder, Transaction, TxOpts, Value as SqlValue};
use serde_json::{json, Map, Value};

const MIGRATIONS: [(&str, &str); 1] = [(
    "0001",
    include_str!("../../../migrations/0001_run_record.sql"),
)];
const DATABASE: &str = "critic";

/// The mutable layer of a run (P3): everything else is fixed at register.
#[derive(Debug, Default, Clone)]
pub struct RunUpdate {
    pub status: Option<String>,
    pub run_state: Option<String>,
    pub void_rule: Option<String>,
    pub ledger: Option<FilePointer>,
    pub cost: Option<FilePointer>,
    pub outcome: Option<Value>,
    pub kos_finding: Option<String>,
}

#[derive(Debug, Default, Clone)]
pub struct ListFilter {
    pub kind: Option<String>,
    pub cohort: Option<String>,
    pub arm: Option<String>,
    pub protocol_role: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Edge {
    pub edge_id: Option<i64>,
    pub child: String,
    pub parent: String,
    pub kind: String,
}

#[derive(Debug, Clone)]
pub struct Replacement {
    pub child: String,
    pub parent: String,
    pub kind: String,
}

pub trait Store {
    /// Create the database and apply every migration not yet applied. Returns
    /// the versions applied by this call.
    fn migrate(&mut self) -> Result<Vec<String>>;
    /// Insert a run, its sessions and its edges in one transaction.
    fn register(
        &mut self,
        run: &ValidRun,
        ledger: Option<FilePointer>,
        cost: Option<FilePointer>,
        by: &str,
    ) -> Result<()>;
    fn show(&mut self, id: &str) -> Result<Option<Value>>;
    fn list(&mut self, filter: &ListFilter) -> Result<Vec<Value>>;
    /// The effective lineage as edges. With `with_corrections` the result also
    /// carries the superseded edges and their corrections, as JSON.
    fn effective_edges(&mut self) -> Result<Vec<Edge>>;
    fn corrections(&mut self) -> Result<Vec<Value>>;
    /// Insert a correction and, with a replacement, the replacement as an ordinary edge,
    /// in one transaction. Returns the correction id and the replacement's edge_id.
    fn correct_edge(
        &mut self,
        edge_id: i64,
        reason: &str,
        replacement: Option<Replacement>,
        by: &str,
    ) -> Result<(i64, Option<i64>)>;
    fn update(&mut self, id: &str, update: &RunUpdate) -> Result<()>;
}

pub struct DoltStore {
    conn: Conn,
}

fn opts(url: &DoltUrl, db: Option<&str>) -> Result<OptsBuilder> {
    let pass = match &url.password_env {
        Some(var) => Some(std::env::var(var).map_err(|_| {
            Error::other(format!(
                "config: password_env names {var}, which is not set"
            ))
        })?),
        None => None,
    };
    Ok(OptsBuilder::new()
        .ip_or_hostname(Some(url.host.clone()))
        .tcp_port(url.port)
        .user(Some(url.user.clone()))
        .pass(pass)
        .db_name(db.map(str::to_string)))
}

impl DoltStore {
    /// Connect to the `critic` database on the configured server. The database
    /// must exist (`critic db migrate` makes it).
    pub fn connect(cfg: &Config) -> Result<DoltStore> {
        let url = cfg.dolt()?;
        let conn = Conn::new(opts(url, Some(DATABASE))?)
            .map_err(|e| Error::other(format!("store: cannot open database {DATABASE} on {}:{} ({e}); run `critic db migrate` first", url.host, url.port)))?;
        Ok(DoltStore { conn })
    }

    /// Connect to the server without a database, for `migrate`.
    pub fn connect_server(cfg: &Config) -> Result<DoltStore> {
        let url = cfg.dolt()?;
        let conn = Conn::new(opts(url, None)?).map_err(|e| {
            Error::other(format!(
                "store: cannot reach {}:{}: {e}",
                url.host, url.port
            ))
        })?;
        Ok(DoltStore { conn })
    }

    /// Direct SQL, for tests that prove the store itself refuses edits (R-f).
    pub fn raw(&mut self) -> &mut Conn {
        &mut self.conn
    }

    fn now(conn: &mut Conn) -> Result<String> {
        let t: Option<String> =
            conn.query_first("SELECT DATE_FORMAT(UTC_TIMESTAMP(), '%Y-%m-%dT%H:%i:%sZ')")?;
        t.ok_or_else(|| Error::other("store: the server returned no time"))
    }
}

/// Split a migration file into statements. A statement ends at a line whose
/// last character is `;`.
fn statements(sql: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    for line in sql.lines() {
        cur.push_str(line);
        cur.push('\n');
        if line.trim_end().ends_with(';') {
            out.push(cur.trim().to_string());
            cur.clear();
        }
    }
    if !cur.trim().is_empty() {
        out.push(cur.trim().to_string());
    }
    out
}

fn json_text(v: &Option<Value>) -> Option<String> {
    v.as_ref().map(|v| v.to_string())
}

fn parse_json_col(s: Option<String>) -> Value {
    match s {
        Some(t) => serde_json::from_str(&t).unwrap_or(Value::String(t)),
        None => Value::Null,
    }
}

fn edges_in(tx: &mut impl Queryable) -> Result<Vec<Edge>> {
    let rows: Vec<(Option<i64>, String, String, String)> = tx.query(
        "SELECT edge_id, child, parent, kind FROM effective_lineage ORDER BY child, parent, kind",
    )?;
    Ok(rows
        .into_iter()
        .map(|(edge_id, child, parent, kind)| Edge {
            edge_id,
            child,
            parent,
            kind,
        })
        .collect())
}

fn pairs(edges: &[Edge]) -> Vec<(String, String)> {
    edges
        .iter()
        .map(|e| (e.child.clone(), e.parent.clone()))
        .collect()
}

fn run_exists(tx: &mut impl Queryable, id: &str) -> Result<bool> {
    let n: Option<i64> = tx.exec_first("SELECT COUNT(*) FROM runs WHERE id = ?", (id,))?;
    Ok(n.unwrap_or(0) > 0)
}

const RUN_COLS: &str = "id, kind, factory, factory_ref, arm, run_id, block, run_order, protocol_role, split, protocol_sha, harness_build, locus, transcript_roots, started_at, ended_at, status, run_state, void_rule, host_class, outcome, metrics, kos_finding, ledger_path, ledger_sha256, cost_path, cost_sha256, registered_at";

fn run_json(row: &mysql::Row) -> Value {
    let s = |name: &str| -> Value {
        row.get::<Option<String>, _>(name)
            .flatten()
            .map(Value::String)
            .unwrap_or(Value::Null)
    };
    let j = |name: &str| -> Value { parse_json_col(row.get::<Option<String>, _>(name).flatten()) };
    let n = |name: &str| -> Value {
        row.get::<Option<i64>, _>(name)
            .flatten()
            .map(Value::from)
            .unwrap_or(Value::Null)
    };
    let pointer = |p: &str, h: &str| -> Value {
        match (
            row.get::<Option<String>, _>(p).flatten(),
            row.get::<Option<String>, _>(h).flatten(),
        ) {
            (Some(path), Some(sha256)) => json!({"path": path, "sha256": sha256}),
            _ => Value::Null,
        }
    };
    let mut m = Map::new();
    m.insert("id".into(), s("id"));
    m.insert("kind".into(), s("kind"));
    m.insert("factory".into(), s("factory"));
    m.insert("factory_ref".into(), j("factory_ref"));
    m.insert("arm".into(), s("arm"));
    m.insert("run_id".into(), s("run_id"));
    m.insert("block".into(), n("block"));
    m.insert("order".into(), n("run_order"));
    m.insert("protocol_role".into(), s("protocol_role"));
    m.insert("split".into(), s("split"));
    m.insert("protocol_sha".into(), s("protocol_sha"));
    m.insert("harness_build".into(), s("harness_build"));
    m.insert("locus".into(), j("locus"));
    m.insert("transcript_roots".into(), j("transcript_roots"));
    m.insert("started_at".into(), s("started_at"));
    m.insert("ended_at".into(), s("ended_at"));
    m.insert("status".into(), s("status"));
    m.insert("run_state".into(), s("run_state"));
    m.insert("void_rule".into(), s("void_rule"));
    m.insert("host_class".into(), s("host_class"));
    m.insert("outcome".into(), j("outcome"));
    m.insert("metrics".into(), j("metrics"));
    m.insert("kos_finding".into(), s("kos_finding"));
    m.insert("ledger".into(), pointer("ledger_path", "ledger_sha256"));
    m.insert("cost".into(), pointer("cost_path", "cost_sha256"));
    m.insert("registered_at".into(), s("registered_at"));
    Value::Object(m)
}

fn insert_edge(
    tx: &mut Transaction<'_>,
    child: &str,
    parent: &str,
    kind: &str,
    now: &str,
    by: &str,
) -> Result<()> {
    tx.exec_drop(
        "INSERT INTO lineage_edges (child, parent, kind, recorded_at, recorded_by) VALUES (?, ?, ?, ?, ?)",
        (child, parent, kind, now, by),
    )?;
    Ok(())
}

impl Store for DoltStore {
    fn migrate(&mut self) -> Result<Vec<String>> {
        self.conn
            .query_drop(format!("CREATE DATABASE IF NOT EXISTS {DATABASE}"))?;
        self.conn.query_drop(format!("USE {DATABASE}"))?;
        self.conn.query_drop(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(16) NOT NULL, applied_at VARCHAR(40) NOT NULL, PRIMARY KEY (version))",
        )?;
        let done: Vec<String> = self.conn.query("SELECT version FROM schema_migrations")?;
        let mut applied = Vec::new();
        for (version, sql) in MIGRATIONS {
            if done.iter().any(|d| d == version) {
                continue;
            }
            for st in statements(sql) {
                self.conn
                    .query_drop(&st)
                    .map_err(|e| Error::other(format!("migration {version}: {e}\n  in: {st}")))?;
            }
            let now = Self::now(&mut self.conn)?;
            self.conn.exec_drop(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, now),
            )?;
            applied.push(version.to_string());
        }
        Ok(applied)
    }

    fn register(
        &mut self,
        run: &ValidRun,
        ledger: Option<FilePointer>,
        cost: Option<FilePointer>,
        by: &str,
    ) -> Result<()> {
        let r = &run.input;
        let now = Self::now(&mut self.conn)?;
        let mut tx = self.conn.start_transaction(TxOpts::default())?;
        if run_exists(&mut tx, &r.id)? {
            return Err(
                Refusal::new("R-a", "id", format!("run {} is already registered", r.id)).into(),
            );
        }
        let mut edges: Vec<(String, &str)> = Vec::new();
        if let Some(p) = &r.parent {
            edges.push((p.clone(), "derived-from"));
        }
        for p in &r.resumed_from {
            edges.push((p.clone(), "resumed-from"));
        }
        for (p, _) in &edges {
            let field = if r.parent.as_deref() == Some(p.as_str()) {
                "parent"
            } else {
                "resumed_from"
            };
            if *p == r.id {
                return Err(Refusal::new("R-e", field, "a run cannot be its own parent").into());
            }
            if !run_exists(&mut tx, p)? {
                return Err(
                    Refusal::new("R-e", field, format!("parent {p} is not registered")).into(),
                );
            }
        }
        let sql = format!(
            "INSERT INTO runs ({RUN_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        );
        let roots = if r.transcript_roots.is_empty() {
            None
        } else {
            Some(json!(r.transcript_roots).to_string())
        };
        let params: Vec<SqlValue> = vec![
            r.id.clone().into(),
            r.kind.clone().into(),
            r.factory.clone().into(),
            json_text(&r.factory_ref).into(),
            r.arm.clone().into(),
            r.run_id.clone().into(),
            r.block.into(),
            r.order.into(),
            r.protocol_role.clone().into(),
            r.split.clone().into(),
            r.protocol_sha.clone().into(),
            r.harness_build.clone().into(),
            json_text(&r.locus).into(),
            roots.into(),
            r.started_at.clone().into(),
            r.ended_at.clone().into(),
            run.status.clone().into(),
            r.run_state.clone().into(),
            r.void_rule.clone().map(|v| v.trim().to_string()).into(),
            r.host_class.clone().into(),
            json_text(&r.outcome).into(),
            json_text(&r.metrics).into(),
            r.kos_finding.clone().into(),
            ledger.as_ref().map(|p| p.path.clone()).into(),
            ledger.as_ref().map(|p| p.sha256.clone()).into(),
            cost.as_ref().map(|p| p.path.clone()).into(),
            cost.as_ref().map(|p| p.sha256.clone()).into(),
            now.clone().into(),
        ];
        tx.exec_drop(sql, params)?;
        for s in &r.sessions {
            let st = s.stamp.clone().unwrap_or_default();
            tx.exec_drop(
                "INSERT INTO run_sessions (run_id_fk, harness, harness_session_id, marvel_session_key, stamp_workspace, stamp_team, stamp_role, stamp_seat, stamp_cluster, stamp_prompt_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (&r.id, &s.harness, &s.harness_session_id, &s.marvel_session_key, &st.workspace, &st.team, &st.role, &st.seat, &st.cluster, &st.prompt_hash),
            )?;
        }
        for (p, kind) in &edges {
            insert_edge(&mut tx, &r.id, p, kind, &now, by)?;
        }
        tx.commit()?;
        Ok(())
    }

    fn show(&mut self, id: &str) -> Result<Option<Value>> {
        let row: Option<mysql::Row> = self
            .conn
            .exec_first(format!("SELECT {RUN_COLS} FROM runs WHERE id = ?"), (id,))?;
        let Some(row) = row else { return Ok(None) };
        let mut v = run_json(&row);
        let sessions: Vec<mysql::Row> = self.conn.exec(
            "SELECT harness, harness_session_id, marvel_session_key, stamp_workspace, stamp_team, stamp_role, stamp_seat, stamp_cluster, stamp_prompt_hash FROM run_sessions WHERE run_id_fk = ? ORDER BY harness, harness_session_id",
            (id,),
        )?;
        let sessions: Vec<Value> = sessions
            .iter()
            .map(|r| {
                let g = |n: &str| -> Value { r.get::<Option<String>, _>(n).flatten().map(Value::String).unwrap_or(Value::Null) };
                json!({
                    "harness": g("harness"), "harness_session_id": g("harness_session_id"), "marvel_session_key": g("marvel_session_key"),
                    "stamp": {"workspace": g("stamp_workspace"), "team": g("stamp_team"), "role": g("stamp_role"),
                              "seat": g("stamp_seat"), "cluster": g("stamp_cluster"), "prompt_hash": g("stamp_prompt_hash")}
                })
            })
            .collect();
        let parents: Vec<(Option<i64>, String, String)> = self.conn.exec(
            "SELECT edge_id, parent, kind FROM effective_lineage WHERE child = ? ORDER BY parent, kind",
            (id,),
        )?;
        v["sessions"] = Value::Array(sessions);
        v["parents"] = Value::Array(
            parents
                .into_iter()
                .map(|(e, p, k)| json!({"edge_id": e, "parent": p, "kind": k}))
                .collect(),
        );
        Ok(Some(v))
    }

    fn list(&mut self, f: &ListFilter) -> Result<Vec<Value>> {
        let mut sql = format!("SELECT {RUN_COLS} FROM runs WHERE 1 = 1");
        let mut params: Vec<SqlValue> = Vec::new();
        for (col, v) in [
            ("kind", &f.kind),
            ("run_id", &f.cohort),
            ("arm", &f.arm),
            ("protocol_role", &f.protocol_role),
        ] {
            if let Some(v) = v {
                sql.push_str(&format!(" AND {col} = ?"));
                params.push(v.clone().into());
            }
        }
        sql.push_str(" ORDER BY started_at, id");
        let rows: Vec<mysql::Row> = self.conn.exec(sql, params)?;
        Ok(rows.iter().map(run_json).collect())
    }

    fn effective_edges(&mut self) -> Result<Vec<Edge>> {
        edges_in(&mut self.conn)
    }

    fn corrections(&mut self) -> Result<Vec<Value>> {
        let rows: Vec<mysql::Row> = self.conn.query(
            "SELECT c.correction_id, c.supersedes, e.child, e.parent, e.kind, c.replacement_edge_id, r.child AS repl_child, r.parent AS repl_parent, r.kind AS repl_kind, c.reason, c.recorded_at, c.recorded_by \
             FROM lineage_corrections c JOIN lineage_edges e ON e.edge_id = c.supersedes \
             LEFT JOIN lineage_edges r ON r.edge_id = c.replacement_edge_id ORDER BY c.correction_id",
        )?;
        Ok(rows
            .iter()
            .map(|r| {
                let g = |n: &str| -> Value { r.get::<Option<String>, _>(n).flatten().map(Value::String).unwrap_or(Value::Null) };
                json!({
                    "correction_id": r.get::<Option<i64>, _>("correction_id").flatten(),
                    "supersedes": {"edge_id": r.get::<Option<i64>, _>("supersedes").flatten(), "child": g("child"), "parent": g("parent"), "kind": g("kind")},
                    "replacement": if g("repl_child").is_null() { Value::Null } else { json!({"edge_id": r.get::<Option<i64>, _>("replacement_edge_id").flatten(), "child": g("repl_child"), "parent": g("repl_parent"), "kind": g("repl_kind")}) },
                    "reason": g("reason"), "recorded_at": g("recorded_at"), "recorded_by": g("recorded_by"),
                })
            })
            .collect())
    }

    fn correct_edge(
        &mut self,
        edge_id: i64,
        reason: &str,
        replacement: Option<Replacement>,
        by: &str,
    ) -> Result<(i64, Option<i64>)> {
        if reason.trim().is_empty() {
            return Err(Refusal::new("R-e", "reason", "a correction needs a reason").into());
        }
        let now = Self::now(&mut self.conn)?;
        let mut tx = self.conn.start_transaction(TxOpts::default())?;
        let exists: Option<i64> = tx.exec_first(
            "SELECT COUNT(*) FROM lineage_edges WHERE edge_id = ?",
            (edge_id,),
        )?;
        if exists.unwrap_or(0) == 0 {
            return Err(Refusal::new("R-e", "edge_id", format!("no edge {edge_id}")).into());
        }
        let done: Option<i64> = tx.exec_first(
            "SELECT COUNT(*) FROM lineage_corrections WHERE supersedes = ?",
            (edge_id,),
        )?;
        if done.unwrap_or(0) > 0 {
            return Err(Refusal::new(
                "R-e",
                "edge_id",
                format!("edge {edge_id} is already superseded"),
            )
            .into());
        }
        let mut after = edges_in(&mut tx)?;
        after.retain(|e| e.edge_id != Some(edge_id));
        if let Some(r) = &replacement {
            check_enum("replace-with kind", &r.kind, &EDGE_KINDS)?;
            for (f, id) in [
                ("replace-with child", &r.child),
                ("replace-with parent", &r.parent),
            ] {
                if !run_exists(&mut tx, id)? {
                    return Err(
                        Refusal::new("R-e", f, format!("run {id} is not registered")).into(),
                    );
                }
            }
            if graph::would_cycle(&pairs(&after), &r.child, &r.parent) {
                return Err(Refusal::new(
                    "R-e",
                    "replace-with",
                    format!("{} derived from {} would close a cycle", r.child, r.parent),
                )
                .into());
            }
        }
        // A replacement is an ordinary edge with its own edge_id, inserted in the same
        // transaction as the correction that names it.
        let replacement_edge_id = match &replacement {
            Some(r) => {
                tx.exec_drop(
                    "INSERT INTO lineage_edges (child, parent, kind, recorded_at, recorded_by) VALUES (?, ?, ?, ?, ?)",
                    (&r.child, &r.parent, &r.kind, &now, by),
                )?;
                let eid: Option<i64> = tx.query_first("SELECT LAST_INSERT_ID()")?;
                eid
            }
            None => None,
        };
        tx.exec_drop(
            "INSERT INTO lineage_corrections (supersedes, replacement_edge_id, reason, recorded_at, recorded_by) VALUES (?, ?, ?, ?, ?)",
            (edge_id, replacement_edge_id, reason, &now, by),
        )?;
        let id: Option<i64> = tx.query_first("SELECT LAST_INSERT_ID()")?;
        tx.commit()?;
        Ok((id.unwrap_or(0), replacement_edge_id))
    }

    fn update(&mut self, id: &str, u: &RunUpdate) -> Result<()> {
        let mut tx = self.conn.start_transaction(TxOpts::default())?;
        let cur: Option<(Option<String>, Option<String>)> =
            tx.exec_first("SELECT run_state, void_rule FROM runs WHERE id = ?", (id,))?;
        let Some((cur_state, cur_rule)) = cur else {
            return Err(Error::other(format!("no run {id}")));
        };
        if let Some(s) = &u.status {
            check_enum("status", s, &STATUSES)?;
            tx.exec_drop("UPDATE runs SET status = ? WHERE id = ?", (s, id))?;
        }
        match (&u.run_state, &u.void_rule) {
            (Some(s), rule) => {
                check_enum("run_state", s, &RUN_STATES)?;
                check_void(Some(s), rule.as_deref())?;
                let rule = rule.as_ref().map(|r| r.trim().to_string());
                tx.exec_drop(
                    "UPDATE runs SET run_state = ?, void_rule = ? WHERE id = ?",
                    (s, rule, id),
                )?;
            }
            (None, Some(rule)) => {
                // A rule alone is valid only for a run already void.
                check_void(cur_state.as_deref(), Some(rule))?;
                tx.exec_drop(
                    "UPDATE runs SET void_rule = ? WHERE id = ?",
                    (rule.trim(), id),
                )?;
            }
            (None, None) => {
                let _ = cur_rule;
            }
        }
        for (path_col, sha_col, p) in [
            ("ledger_path", "ledger_sha256", &u.ledger),
            ("cost_path", "cost_sha256", &u.cost),
        ] {
            if let Some(p) = p {
                tx.exec_drop(
                    format!("UPDATE runs SET {path_col} = ?, {sha_col} = ? WHERE id = ?"),
                    (&p.path, &p.sha256, id),
                )?;
            }
        }
        if let Some(o) = &u.outcome {
            tx.exec_drop(
                "UPDATE runs SET outcome = ? WHERE id = ?",
                (o.to_string(), id),
            )?;
        }
        if let Some(k) = &u.kos_finding {
            tx.exec_drop("UPDATE runs SET kos_finding = ? WHERE id = ?", (k, id))?;
        }
        tx.commit()?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::statements;

    #[test]
    fn statements_split_on_a_closing_semicolon_line() {
        let s = statements("CREATE TABLE a (\n  x INT\n);\nCREATE TRIGGER t BEFORE UPDATE ON a FOR EACH ROW SIGNAL SQLSTATE '45000';\n");
        assert_eq!(s.len(), 2);
        assert!(s[0].starts_with("CREATE TABLE a"));
        assert!(s[1].starts_with("CREATE TRIGGER"));
    }
}
