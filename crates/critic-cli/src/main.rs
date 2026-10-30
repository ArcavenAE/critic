//! `critic`: the run record (component 1). Human text by default, JSON under
//! `--json`. Exit 0 on success, 1 on a refusal, 2 on a usage or store error.

use clap::{Args, Parser, Subcommand};
use critic_core::config::Config;
use critic_core::doctor::run_references;
use critic_core::error::{Error, Refusal, Result};
use critic_core::graph;
use critic_core::model::{reject_host_names, validate, RunInput};
use critic_core::paths::{pointer, runtime_root_outside_git};
use critic_core::store::{DoltStore, ListFilter, Replacement, RunUpdate, Store};
use serde_json::{json, Value};
use std::path::PathBuf;
use std::process::ExitCode;

const REGISTER_FIELDS: &str = "Fields (design section 3; an unknown field is an error):
  id (required)       lowercase, no slash; unique
  kind (required)     legion | spike | fork | trial
  factory, factory_ref, arm, run_id (the cohort), block, order, protocol_role, split (search | validation | test)
  protocol_sha, harness_build, locus, started_at, ended_at, kos_finding, metrics, outcome
  status              active (default) | archived | abandoned
  run_state           started | completed | stalled | crashed | timed-out | limit-stopped | void
  void_rule           the protocol rule that voided the run; required with void, refused otherwise
  host_class          one of the configured host_classes; a host name is refused at any depth
  parent              one derived-from edge to a registered run
  resumed_from        a list of resumed-from edges to registered runs
  transcript_roots    a list of absolute paths under the runtime root
  ledger, cost        a file under the runtime root; stored with its sha256, never parsed
  sessions            a list of {harness, harness_session_id, marvel_session_key, stamp}; stamp is optional:
                      {workspace, team, role, seat, cluster, prompt_hash}, every part optional";

#[derive(Parser)]
#[command(
    name = "critic",
    version,
    about = "The run record: one id per run, its sessions, its append-only lineage"
)]
struct Cli {
    /// Config file (default: $XDG_CONFIG_HOME/critic/config.toml).
    #[arg(long, global = true)]
    config: Option<PathBuf>,
    /// Print JSON instead of text.
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
#[allow(clippy::large_enum_variant)]
enum Cmd {
    /// Register, show, list and walk runs.
    #[command(subcommand)]
    Run(RunCmd),
    /// Database setup.
    #[command(subcommand)]
    Db(DbCmd),
    /// Checks on the environment critic runs in.
    #[command(subcommand)]
    Doctor(DoctorCmd),
}

#[derive(Subcommand)]
enum DbCmd {
    /// Create the critic database on the configured server and apply the migrations.
    Migrate,
}

#[derive(Subcommand)]
enum DoctorCmd {
    /// Exit 1, naming each line, when a recipe in the orchestrator's justfile reads run/.
    Isolation {
        /// The orchestrator checkout (its justfile is read), or a justfile path.
        #[arg(long)]
        orc: PathBuf,
    },
}

#[derive(Subcommand)]
#[allow(clippy::large_enum_variant)]
enum RunCmd {
    /// Validate a run from a YAML or JSON file and insert it, its sessions and its edges in one transaction. Prints the id.
    #[command(after_help = REGISTER_FIELDS)]
    Register {
        /// The file to read.
        file: PathBuf,
    },
    /// Print a run, its sessions with their seat stamps, its effective parents, its ledger and cost pointers, and its transcript roots.
    Show {
        /// The run id.
        id: String,
    },
    /// One line per run, sorted by started_at then id.
    List {
        #[arg(long)]
        kind: Option<String>,
        /// The cohort: the run_id field that groups a batch or series.
        #[arg(long)]
        cohort: Option<String>,
        #[arg(long)]
        arm: Option<String>,
        #[arg(long)]
        protocol_role: Option<String>,
    },
    /// Walk the effective lineage of a run.
    Lineage {
        /// The run id.
        id: String,
        /// Follow parents (the default).
        #[arg(long, conflicts_with = "descendants")]
        ancestors: bool,
        /// Follow children.
        #[arg(long)]
        descendants: bool,
        /// Also print superseded edges and their corrections.
        #[arg(long)]
        with_corrections: bool,
    },
    /// Insert a correction that supersedes an edge, with a reason and an optional replacement edge (inserted with its own edge_id). The only way an edge changes.
    CorrectEdge {
        /// The edge to supersede (its id is printed by `critic run show` and by `correct-edge` for a replacement).
        edge_id: i64,
        /// Why the edge is wrong; not empty.
        #[arg(long)]
        reason: String,
        /// CHILD,PARENT,KIND (kind: derived-from or resumed-from).
        #[arg(long)]
        replace_with: Option<String>,
    },
    /// Change the mutable layer of a run: status, run_state with its void_rule, the ledger and cost pointers, the outcome, the kos finding.
    Update(UpdateArgs),
}

#[derive(Args)]
struct UpdateArgs {
    /// The run to change.
    id: String,
    /// active | archived | abandoned.
    #[arg(long)]
    status: Option<String>,
    /// started | completed | stalled | crashed | timed-out | limit-stopped | void.
    #[arg(long)]
    run_state: Option<String>,
    /// The protocol rule that voided the run; valid with --run-state void.
    #[arg(long)]
    void_rule: Option<String>,
    /// A file under the runtime root; stored with its sha256, never parsed.
    #[arg(long)]
    ledger: Option<String>,
    /// A file under the runtime root; stored with its sha256, never parsed.
    #[arg(long)]
    cost: Option<String>,
    /// The outcome, as JSON.
    #[arg(long)]
    outcome: Option<String>,
    #[arg(long)]
    kos_finding: Option<String>,
    // Fixed at register (P3). Present so a try is refused with the rule, not a usage error.
    #[arg(long, hide = true)]
    kind: Option<String>,
    #[arg(long, hide = true)]
    factory: Option<String>,
    #[arg(long, hide = true)]
    factory_ref: Option<String>,
    #[arg(long, hide = true)]
    arm: Option<String>,
    #[arg(long, hide = true)]
    run_id: Option<String>,
    #[arg(long, hide = true)]
    block: Option<String>,
    #[arg(long, hide = true)]
    order: Option<String>,
    #[arg(long, hide = true)]
    protocol_role: Option<String>,
    #[arg(long, hide = true)]
    split: Option<String>,
    #[arg(long, hide = true)]
    protocol_sha: Option<String>,
    #[arg(long, hide = true)]
    harness_build: Option<String>,
    #[arg(long = "new-id", hide = true)]
    new_id: Option<String>,
}

fn recorded_by() -> String {
    std::env::var("CRITIC_RECORDED_BY")
        .ok()
        .filter(|v| !v.is_empty())
        .or_else(|| std::env::var("USER").ok().filter(|v| !v.is_empty()))
        .unwrap_or_else(|| "unknown".to_string())
}

fn emit(json_mode: bool, value: &Value, text: impl FnOnce() -> String) {
    if json_mode {
        println!(
            "{}",
            serde_json::to_string_pretty(value).unwrap_or_default()
        );
    } else {
        println!("{}", text());
    }
}

fn s(v: &Value) -> String {
    match v {
        Value::Null => "-".to_string(),
        Value::String(t) => t.clone(),
        other => other.to_string(),
    }
}

fn run_line(r: &Value) -> String {
    format!(
        "{}  {}  arm={}  cohort={}  state={}  started={}",
        s(&r["id"]),
        s(&r["kind"]),
        s(&r["arm"]),
        s(&r["run_id"]),
        s(&r["run_state"]),
        s(&r["started_at"])
    )
}

fn show_text(r: &Value) -> String {
    let mut out = String::new();
    let mut line = |k: &str, v: String| out.push_str(&format!("{k}: {v}\n"));
    for k in [
        "id",
        "kind",
        "factory",
        "factory_ref",
        "arm",
        "run_id",
        "block",
        "order",
        "protocol_role",
        "split",
        "protocol_sha",
        "harness_build",
        "locus",
        "started_at",
        "ended_at",
        "status",
        "run_state",
        "void_rule",
        "host_class",
        "outcome",
        "metrics",
        "kos_finding",
        "registered_at",
    ] {
        line(k, s(&r[k]));
    }
    for k in ["ledger", "cost"] {
        let p = &r[k];
        line(
            k,
            if p.is_null() {
                "-".into()
            } else {
                format!("{} sha256:{}", s(&p["path"]), s(&p["sha256"]))
            },
        );
    }
    line(
        "transcript_roots",
        r["transcript_roots"]
            .as_array()
            .map(|a| a.iter().map(s).collect::<Vec<_>>().join(", "))
            .unwrap_or_else(|| "-".into()),
    );
    out.push_str("sessions:\n");
    for x in r["sessions"].as_array().into_iter().flatten() {
        let st = &x["stamp"];
        out.push_str(&format!(
            "  {} {} marvel={} stamp[workspace={} team={} role={} seat={} cluster={} prompt_hash={}]\n",
            s(&x["harness"]), s(&x["harness_session_id"]), s(&x["marvel_session_key"]),
            s(&st["workspace"]), s(&st["team"]), s(&st["role"]), s(&st["seat"]), s(&st["cluster"]), s(&st["prompt_hash"])
        ));
    }
    out.push_str("parents:\n");
    for p in r["parents"].as_array().into_iter().flatten() {
        out.push_str(&format!(
            "  {} ({}, edge {})\n",
            s(&p["parent"]),
            s(&p["kind"]),
            s(&p["edge_id"])
        ));
    }
    out.trim_end().to_string()
}

fn load_yaml_or_json(path: &std::path::Path) -> Result<Value> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| Error::other(format!("cannot read {}: {e}", path.display())))?;
    let y: serde_yaml::Value = serde_yaml::from_str(&text)
        .map_err(|e| Error::other(format!("{}: {e}", path.display())))?;
    serde_json::to_value(y).map_err(|e| Error::other(format!("{}: {e}", path.display())))
}

fn register(cfg: &Config, store: &mut dyn Store, file: &std::path::Path) -> Result<String> {
    let raw = load_yaml_or_json(file)?;
    reject_host_names(&raw)?;
    let input: RunInput = serde_json::from_value(raw)
        .map_err(|e| Error::other(format!("{}: {e}", file.display())))?;
    let root = cfg.runtime_root()?.to_path_buf();
    runtime_root_outside_git(&root)?;
    let valid = validate(input, cfg)?;
    let ledger = valid
        .input
        .ledger
        .as_deref()
        .map(|p| pointer(&root, "ledger", p))
        .transpose()?;
    let cost = valid
        .input
        .cost
        .as_deref()
        .map(|p| pointer(&root, "cost", p))
        .transpose()?;
    store.register(&valid, ledger, cost, &recorded_by())?;
    Ok(valid.input.id)
}

fn update(cfg: &Config, store: &mut dyn Store, a: &UpdateArgs) -> Result<()> {
    let fixed = [
        ("new-id", &a.new_id),
        ("kind", &a.kind),
        ("factory", &a.factory),
        ("factory_ref", &a.factory_ref),
        ("arm", &a.arm),
        ("run_id", &a.run_id),
        ("block", &a.block),
        ("order", &a.order),
        ("protocol_role", &a.protocol_role),
        ("split", &a.split),
        ("protocol_sha", &a.protocol_sha),
        ("harness_build", &a.harness_build),
    ];
    for (name, v) in fixed {
        if v.is_some() {
            let field = if name == "new-id" { "id" } else { name };
            return Err(Refusal::new(
                "P3",
                field,
                "fixed at register; a run's identity fields never change",
            )
            .into());
        }
    }
    let root = cfg.runtime_root().ok().map(|p| p.to_path_buf());
    let ptr =
        |field: &str, p: &Option<String>| -> Result<Option<critic_core::model::FilePointer>> {
            match p {
                Some(p) => Ok(Some(pointer(
                    root.as_deref()
                        .ok_or_else(|| Error::other("config: runtime_root is not set"))?,
                    field,
                    p,
                )?)),
                None => Ok(None),
            }
        };
    let outcome = match &a.outcome {
        Some(t) => Some(
            serde_json::from_str::<Value>(t)
                .map_err(|e| Error::other(format!("--outcome is not JSON: {e}")))?,
        ),
        None => None,
    };
    let u = RunUpdate {
        status: a.status.clone(),
        run_state: a.run_state.clone(),
        void_rule: a.void_rule.clone(),
        ledger: ptr("ledger", &a.ledger)?,
        cost: ptr("cost", &a.cost)?,
        outcome,
        kos_finding: a.kos_finding.clone(),
    };
    store.update(&a.id, &u)
}

fn lineage(
    store: &mut dyn Store,
    json_mode: bool,
    id: &str,
    descendants: bool,
    with_corrections: bool,
) -> Result<()> {
    if store.show(id)?.is_none() {
        return Err(Error::other(format!("no run {id}")));
    }
    let edges = store.effective_edges()?;
    let pairs: Vec<(String, String)> = edges
        .iter()
        .map(|e| (e.child.clone(), e.parent.clone()))
        .collect();
    let ids = graph::walk(&pairs, id, !descendants);
    let corrections = if with_corrections {
        store.corrections()?
    } else {
        vec![]
    };
    let value = json!({
        "id": id,
        "direction": if descendants { "descendants" } else { "ancestors" },
        "runs": ids,
        "corrections": corrections,
    });
    emit(json_mode, &value, || {
        let mut out = format!(
            "{} of {id}:",
            if descendants {
                "descendants"
            } else {
                "ancestors"
            }
        );
        if ids.is_empty() {
            out.push_str(" none");
        }
        for i in &ids {
            out.push_str(&format!("\n  {i}"));
        }
        for c in &corrections {
            let sup = &c["supersedes"];
            out.push_str(&format!(
                "\ncorrection {}: edge {} ({} derived from {}, {}) superseded: {}{}",
                s(&c["correction_id"]),
                s(&sup["edge_id"]),
                s(&sup["child"]),
                s(&sup["parent"]),
                s(&sup["kind"]),
                s(&c["reason"]),
                if c["replacement"].is_null() {
                    String::new()
                } else {
                    format!(
                        "; replaced by {} derived from {} ({})",
                        s(&c["replacement"]["child"]),
                        s(&c["replacement"]["parent"]),
                        s(&c["replacement"]["kind"])
                    )
                }
            ));
        }
        out
    });
    Ok(())
}

fn isolation(orc: &std::path::Path, json_mode: bool) -> Result<bool> {
    let path = if orc.is_dir() {
        orc.join("justfile")
    } else {
        orc.to_path_buf()
    };
    let text = std::fs::read_to_string(&path)
        .map_err(|e| Error::other(format!("cannot read {}: {e}", path.display())))?;
    let refs = run_references(&text);
    let value = json!({"justfile": path.display().to_string(), "references": refs.iter().map(|r| json!({"line": r.line, "recipe": r.recipe, "text": r.text})).collect::<Vec<_>>()});
    emit(json_mode, &value, || {
        if refs.is_empty() {
            format!(
                "isolation holds: no recipe in {} reads run/",
                path.display()
            )
        } else {
            refs.iter()
                .map(|r| {
                    format!(
                        "{}:{}: recipe {} reads run/: {}",
                        path.display(),
                        r.line,
                        r.recipe,
                        r.text
                    )
                })
                .collect::<Vec<_>>()
                .join("\n")
        }
    });
    Ok(refs.is_empty())
}

fn dispatch(cli: Cli) -> Result<i32> {
    let json_mode = cli.json;
    if let Cmd::Doctor(DoctorCmd::Isolation { orc }) = &cli.cmd {
        return Ok(if isolation(orc, json_mode)? { 0 } else { 1 });
    }
    let cfg = Config::load(cli.config.as_deref())?;
    match cli.cmd {
        Cmd::Db(DbCmd::Migrate) => {
            let mut st = DoltStore::connect_server(&cfg)?;
            let applied = st.migrate()?;
            emit(json_mode, &json!({"applied": applied}), || {
                if applied.is_empty() {
                    "schema is current".to_string()
                } else {
                    format!("applied: {}", applied.join(", "))
                }
            });
        }
        Cmd::Run(run) => {
            let mut st = DoltStore::connect(&cfg)?;
            match run {
                RunCmd::Register { file } => {
                    let id = register(&cfg, &mut st, &file)?;
                    emit(json_mode, &json!({"id": id}), || id.clone());
                }
                RunCmd::Show { id } => {
                    let r = st
                        .show(&id)?
                        .ok_or_else(|| Error::other(format!("no run {id}")))?;
                    emit(json_mode, &r, || show_text(&r));
                }
                RunCmd::List {
                    kind,
                    cohort,
                    arm,
                    protocol_role,
                } => {
                    let rows = st.list(&ListFilter {
                        kind,
                        cohort,
                        arm,
                        protocol_role,
                    })?;
                    emit(json_mode, &Value::Array(rows.clone()), || {
                        rows.iter().map(run_line).collect::<Vec<_>>().join("\n")
                    });
                }
                RunCmd::Lineage {
                    id,
                    ancestors: _,
                    descendants,
                    with_corrections,
                } => {
                    lineage(&mut st, json_mode, &id, descendants, with_corrections)?;
                }
                RunCmd::CorrectEdge {
                    edge_id,
                    reason,
                    replace_with,
                } => {
                    let repl = match replace_with {
                        Some(t) => {
                            let p: Vec<&str> = t.split(',').collect();
                            if p.len() != 3 {
                                return Err(Error::other("--replace-with takes CHILD,PARENT,KIND"));
                            }
                            Some(Replacement {
                                child: p[0].to_string(),
                                parent: p[1].to_string(),
                                kind: p[2].to_string(),
                            })
                        }
                        None => None,
                    };
                    let (cid, new_edge) =
                        st.correct_edge(edge_id, &reason, repl, &recorded_by())?;
                    emit(
                        json_mode,
                        &json!({"correction_id": cid, "replacement_edge_id": new_edge}),
                        || match new_edge {
                            Some(e) => format!("correction {cid} recorded; replacement edge {e}"),
                            None => format!("correction {cid} recorded"),
                        },
                    );
                }
                RunCmd::Update(a) => {
                    update(&cfg, &mut st, &a)?;
                    emit(json_mode, &json!({"updated": a.id}), || {
                        format!("updated {}", a.id)
                    });
                }
            }
        }
        Cmd::Doctor(_) => unreachable!("handled above"),
    }
    Ok(0)
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    match dispatch(cli) {
        Ok(code) => ExitCode::from(code as u8),
        Err(e) => {
            eprintln!("critic: {e}");
            ExitCode::from(e.exit_code() as u8)
        }
    }
}
