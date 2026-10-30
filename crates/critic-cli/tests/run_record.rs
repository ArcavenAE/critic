//! Component 1 against a throwaway Dolt server: every refusal in the spec's
//! section 6 (each one reads the store afterwards to show nothing changed), the
//! register/show/list round trip, lineage corrections, the mutable layer, and the
//! isolation verb on two fixture justfiles.

mod common;
use common::{fixture, text, Env};
use critic_core::store::Store;
use serde_json::json;

const TRIAL: &str = "id: probe-1\nkind: trial\nfactory: vsdd\narm: one-session\nrun_id: series-1\nprotocol_role: series\nstarted_at: '2026-10-30T10:00:00Z'\n";

fn run_with(extra: &str) -> String {
    format!("{TRIAL}{extra}")
}

fn refused(env: &Env, body: &str, rule: &str, field: &str) {
    let before = env.run_ids();
    let out = env.register(body);
    assert_eq!(
        out.status.code(),
        Some(1),
        "expected a refusal: {}",
        text(&out)
    );
    let t = text(&out);
    assert!(t.contains(rule), "names the rule {rule}: {t}");
    assert!(t.contains(field), "names the field {field}: {t}");
    assert_eq!(
        env.run_ids(),
        before,
        "the store is unchanged after a refusal"
    );
}

#[test]
fn migrate_creates_the_schema_once() {
    let env = Env::start();
    let again = env.json(&["db", "migrate"]);
    assert_eq!(
        again["applied"],
        json!([]),
        "a second migrate applies nothing"
    );
}

#[test]
fn an_unset_dolt_url_is_a_usage_error_and_reaches_no_server() {
    let mut env = Env::start();
    env.write_config(
        &format!("runtime_root = {:?}\n", env.runtime.display().to_string()),
        false,
    );
    let out = env.critic(&["run", "list"]);
    assert_eq!(out.status.code(), Some(2));
    assert!(text(&out).contains("dolt_url"), "{}", text(&out));
}

#[test]
fn register_show_and_list_round_trip_a_trial_with_two_sessions_an_edge_and_pointers() {
    let env = Env::start();
    assert!(env
        .register("id: seed-1\nkind: trial\nprotocol_role: seed\n")
        .status
        .success());
    let ledger = env.runtime_file("probe-1/ledger.json", "{\"rows\": 3}\n");
    let cost = env.runtime_file("probe-1/cost.json", "{\"usd\": 1.5}\n");
    let root = env.runtime.display().to_string();
    let body = format!(
        "{TRIAL}block: 2\norder: 1\nprotocol_sha: abc123\nharness_build: build-9\nhost_class: probe-host\nresumed_from: [seed-1]\n\
         factory_ref: {{pack: v1, commit: deadbeef}}\nlocus: {{repo: example/test-project, start: aaa, end: bbb}}\n\
         transcript_roots: ['{root}/probe-1/transcripts']\nrun_state: completed\noutcome: {{accepted: 4, pass_rate: 0.75}}\n\
         ledger: '{ledger}'\ncost: '{cost}'\nkos_finding: finding-1\n\
         sessions:\n  - harness: claude\n    harness_session_id: s-1\n    marvel_session_key: aae/seat-a\n    stamp: {{workspace: aae, team: t, role: builder, seat: seat-a, cluster: local, prompt_hash: 'sha256:aa'}}\n  - harness: claude\n    harness_session_id: s-2\n"
    );
    let out = env.register(&body);
    assert!(out.status.success(), "{}", text(&out));
    assert_eq!(String::from_utf8_lossy(&out.stdout).trim(), "probe-1");

    let shown = env.json(&["run", "show", "probe-1"]);
    assert_eq!(shown["kind"], "trial");
    assert_eq!(shown["block"], 2);
    assert_eq!(shown["order"], 1);
    assert_eq!(shown["status"], "active");
    assert_eq!(shown["factory_ref"]["pack"], "v1");
    assert_eq!(shown["ledger"]["path"], ledger.as_str());
    assert_eq!(shown["ledger"]["sha256"].as_str().unwrap().len(), 64);
    assert_eq!(shown["cost"]["sha256"].as_str().unwrap().len(), 64);
    assert_eq!(
        shown["transcript_roots"],
        json!([format!("{root}/probe-1/transcripts")])
    );
    let parents = shown["parents"].as_array().unwrap();
    assert_eq!(parents.len(), 1);
    assert_eq!(parents[0]["parent"], "seed-1");
    assert_eq!(parents[0]["kind"], "resumed-from");
    assert!(
        parents[0]["edge_id"].is_i64(),
        "an edge shows its id, so it can be corrected"
    );
    let sessions = shown["sessions"].as_array().unwrap();
    assert_eq!(sessions.len(), 2);
    assert_eq!(sessions[0]["stamp"]["seat"], "seat-a");
    assert_eq!(sessions[0]["stamp"]["prompt_hash"], "sha256:aa");
    assert!(
        sessions[1]["stamp"]["seat"].is_null(),
        "an unstamped session is valid and prints no stamp"
    );

    let human = text(&env.critic(&["run", "show", "probe-1"]));
    assert!(
        human.contains("seat=seat-a") && human.contains("prompt_hash=sha256:aa"),
        "{human}"
    );
    assert!(human.contains("seed-1 (resumed-from, edge "), "{human}");
    assert!(human.contains("sha256:"), "{human}");

    let by_cohort = env.json(&[
        "run",
        "list",
        "--cohort",
        "series-1",
        "--arm",
        "one-session",
        "--protocol-role",
        "series",
        "--kind",
        "trial",
    ]);
    assert_eq!(by_cohort.as_array().unwrap().len(), 1);
    assert_eq!(env.run_ids().len(), 2);
}

#[test]
fn r_a_a_second_register_of_an_id_is_refused() {
    let env = Env::start();
    env.register_ok(TRIAL);
    refused(&env, TRIAL, "R-a", "id");
    assert_eq!(env.run_ids(), vec!["probe-1"]);
}

#[test]
fn r_b_a_void_needs_its_rule_and_only_a_void_carries_one() {
    let env = Env::start();
    refused(&env, &run_with("run_state: void\n"), "R-b", "void_rule");
    refused(
        &env,
        &run_with("run_state: void\nvoid_rule: '   '\n"),
        "R-b",
        "void_rule",
    );
    refused(
        &env,
        &run_with("run_state: completed\nvoid_rule: s8.5\n"),
        "R-b",
        "void_rule",
    );
    refused(&env, &run_with("void_rule: s8.5\n"), "R-b", "void_rule");
    assert!(env
        .register(&run_with("run_state: void\nvoid_rule: s8.5\n"))
        .status
        .success());
}

#[test]
fn r_c_an_id_is_lowercase_has_no_slash_and_is_not_empty() {
    let env = Env::start();
    for bad in ["''", "Probe-1", "a/b", "a b"] {
        refused(&env, &format!("id: {bad}\nkind: trial\n"), "R-c", "id");
    }
}

#[test]
fn r_d_enums_are_closed() {
    let env = Env::start();
    refused(&env, "id: x1\nkind: bogus\n", "R-d", "kind");
    refused(
        &env,
        "id: x1\nkind: trial\nrun_state: napping\n",
        "R-d",
        "run_state",
    );
    refused(&env, "id: x1\nkind: trial\nstatus: gone\n", "R-d", "status");
    refused(&env, "id: x1\nkind: trial\nsplit: dev\n", "R-d", "split");
    assert!(env
        .register("id: x1\nkind: trial\nsplit: validation\n")
        .status
        .success());
    assert_eq!(env.json(&["run", "show", "x1"])["split"], "validation");
}

#[test]
fn r_e_lineage_refuses_a_self_edge_a_missing_parent_and_a_cycle() {
    let env = Env::start();
    refused(&env, "id: x1\nkind: trial\nparent: x1\n", "R-e", "parent");
    refused(
        &env,
        "id: x1\nkind: trial\nparent: ghost\n",
        "R-e",
        "parent",
    );
    env.register_ok("id: a\nkind: trial\n");
    env.register_ok("id: b\nkind: trial\nparent: a\n");
    env.register_ok("id: c\nkind: trial\nparent: b\n");
    env.register_ok("id: z\nkind: trial\n");
    env.register_ok("id: e\nkind: trial\nparent: z\n");
    // The chain is c -> b -> a. Replacing the unrelated edge e -> z with "a derived from c" would close it.
    let edges = env.store().effective_edges().unwrap();
    let e_edge = edges
        .iter()
        .find(|x| x.child == "e")
        .unwrap()
        .edge_id
        .unwrap()
        .to_string();
    let out = env.critic(&[
        "run",
        "correct-edge",
        &e_edge,
        "--reason",
        "test",
        "--replace-with",
        "a,c,derived-from",
    ]);
    assert_eq!(out.status.code(), Some(1), "{}", text(&out));
    assert!(
        text(&out).contains("R-e") && text(&out).contains("cycle"),
        "{}",
        text(&out)
    );
    assert_eq!(
        env.store().effective_edges().unwrap().len(),
        3,
        "nothing changed"
    );
    let ok = env.critic(&[
        "run",
        "correct-edge",
        &e_edge,
        "--reason",
        "test",
        "--replace-with",
        "z,a,derived-from",
    ]);
    assert!(
        ok.status.success(),
        "a replacement that closes no cycle is accepted: {}",
        text(&ok)
    );
}

#[test]
fn r_f_the_store_refuses_a_direct_update_or_delete_on_either_lineage_table() {
    use mysql::prelude::Queryable;
    let env = Env::start();
    env.register_ok("id: a\nkind: trial\n");
    assert!(env
        .register("id: b\nkind: trial\nparent: a\n")
        .status
        .success());
    let edge = env.store().effective_edges().unwrap()[0].edge_id.unwrap();
    assert!(env
        .critic(&[
            "run",
            "correct-edge",
            &edge.to_string(),
            "--reason",
            "wrong parent"
        ])
        .status
        .success());
    let mut st = env.store();
    for sql in [
        "UPDATE lineage_edges SET kind = 'resumed-from'",
        "DELETE FROM lineage_edges",
        "UPDATE lineage_corrections SET reason = 'edited'",
        "DELETE FROM lineage_corrections",
    ] {
        let err = st.raw().query_drop(sql).expect_err(sql);
        assert!(
            err.to_string().contains("lineage_is_append_only"),
            "{sql}: {err}"
        );
    }
    let n: Option<i64> = st
        .raw()
        .query_first("SELECT COUNT(*) FROM lineage_edges")
        .unwrap();
    let c: Option<i64> = st
        .raw()
        .query_first("SELECT COUNT(*) FROM lineage_corrections")
        .unwrap();
    assert_eq!((n, c), (Some(1), Some(1)), "every row survived");
}

#[test]
fn r_g_paths_stay_under_the_runtime_root_and_the_root_stays_out_of_a_checkout() {
    let mut env = Env::start();
    let outside = env.dir.path().join("elsewhere.json");
    std::fs::write(&outside, "{}").unwrap();
    let o = outside.display().to_string();
    refused(
        &env,
        &run_with(&format!("transcript_roots: ['{o}']\n")),
        "R-g",
        "transcript_roots",
    );
    refused(
        &env,
        &run_with(&format!("ledger: '{o}'\n")),
        "R-g",
        "ledger",
    );
    refused(&env, &run_with(&format!("cost: '{o}'\n")), "R-g", "cost");
    refused(
        &env,
        &run_with("ledger: relative/path.json\n"),
        "R-g",
        "ledger",
    );
    let repo = env.dir.path().join("checkout");
    std::fs::create_dir_all(repo.join(".git")).unwrap();
    std::fs::create_dir_all(repo.join("runtime")).unwrap();
    let extra = format!(
        "runtime_root = {:?}\n",
        repo.join("runtime").display().to_string()
    );
    let (port, cfg) = (env.port, env.config.clone());
    std::fs::write(
        &cfg,
        format!("{extra}[dolt_url]\nhost = \"127.0.0.1\"\nport = {port}\nuser = \"root\"\n"),
    )
    .unwrap();
    let before = env.run_ids();
    let out = env.register(TRIAL);
    assert_eq!(out.status.code(), Some(1), "{}", text(&out));
    assert!(
        text(&out).contains("R-g") && text(&out).contains("runtime_root"),
        "{}",
        text(&out)
    );
    assert_eq!(env.run_ids(), before);
    env.write_config("", true);
}

#[test]
fn r_h_host_names_never_enter_the_record() {
    let env = Env::start();
    refused(&env, &run_with("host: some-machine\n"), "R-h", "host");
    refused(
        &env,
        &run_with("hostname: some-machine\n"),
        "R-h",
        "hostname",
    );
    refused(
        &env,
        &run_with("metrics: {host_name: some-machine}\n"),
        "R-h",
        "metrics.host_name",
    );
    refused(
        &env,
        &run_with(
            "sessions:\n  - harness: h\n    harness_session_id: s\n    stamp: {hostname: x}\n",
        ),
        "R-h",
        "stamp.hostname",
    );
    refused(&env, &run_with("host_class: laptop\n"), "R-h", "host_class");
    assert!(env
        .register(&run_with("host_class: probe-host\n"))
        .status
        .success());
}

#[test]
fn lineage_corrections_change_the_effective_view_and_keep_the_old_rows() {
    use mysql::prelude::Queryable;
    let env = Env::start();
    for body in [
        "id: seed-a\nkind: trial\n",
        "id: seed-b\nkind: trial\n",
        "id: child\nkind: trial\nresumed_from: [seed-a]\n",
    ] {
        env.register_ok(body);
    }
    let anc = env.json(&["run", "lineage", "child"]);
    assert_eq!(anc["runs"], json!(["seed-a"]));
    let edge = env.store().effective_edges().unwrap()[0].edge_id.unwrap();
    let c = env.critic(&[
        "run",
        "correct-edge",
        &edge.to_string(),
        "--reason",
        "wrong seed",
        "--replace-with",
        "child,seed-b,resumed-from",
    ]);
    assert!(c.status.success(), "{}", text(&c));
    assert_eq!(
        env.json(&["run", "lineage", "child"])["runs"],
        json!(["seed-b"]),
        "the effective lineage follows the correction"
    );
    assert_eq!(
        env.json(&["run", "lineage", "seed-b", "--descendants"])["runs"],
        json!(["child"])
    );
    let with = env.json(&["run", "lineage", "child", "--with-corrections"]);
    assert_eq!(with["corrections"][0]["reason"], "wrong seed");
    assert_eq!(
        with["corrections"][0]["supersedes"]["parent"], "seed-a",
        "the superseded edge is still reported"
    );
    let human = text(&env.critic(&["run", "lineage", "child", "--with-corrections"]));
    assert!(
        human.contains("seed-a") && human.contains("replaced by child derived from seed-b"),
        "{human}"
    );
    let n: Option<i64> = env
        .store()
        .raw()
        .query_first("SELECT COUNT(*) FROM lineage_edges")
        .unwrap();
    assert_eq!(n, Some(1), "the superseded row is still in the table");
    let again = env.critic(&[
        "run",
        "correct-edge",
        &edge.to_string(),
        "--reason",
        "twice",
    ]);
    assert_eq!(again.status.code(), Some(1), "an edge is superseded once");
    let empty = env.critic(&["run", "correct-edge", &edge.to_string(), "--reason", ""]);
    assert_eq!(empty.status.code(), Some(1));
}

#[test]
fn update_changes_only_the_mutable_layer() {
    let env = Env::start();
    env.register_ok(TRIAL);
    assert!(env
        .critic(&["run", "update", "probe-1", "--status", "archived"])
        .status
        .success());
    assert!(env
        .critic(&[
            "run",
            "update",
            "probe-1",
            "--run-state",
            "void",
            "--void-rule",
            "s8.5"
        ])
        .status
        .success());
    let v = env.json(&["run", "show", "probe-1"]);
    assert_eq!(
        (
            v["status"].as_str(),
            v["run_state"].as_str(),
            v["void_rule"].as_str()
        ),
        (Some("archived"), Some("void"), Some("s8.5"))
    );
    assert_eq!(
        env.critic(&["run", "update", "probe-1", "--run-state", "void"])
            .status
            .code(),
        Some(1),
        "a void without a rule"
    );
    assert!(env
        .critic(&["run", "update", "probe-1", "--run-state", "completed"])
        .status
        .success());
    assert!(
        env.json(&["run", "show", "probe-1"])["void_rule"].is_null(),
        "leaving void clears its rule"
    );
    let ledger = env.runtime_file("probe-1/ledger.json", "{}\n");
    assert!(env
        .critic(&[
            "run",
            "update",
            "probe-1",
            "--ledger",
            &ledger,
            "--outcome",
            "{\"accepted\": 2}",
            "--kos-finding",
            "finding-9"
        ])
        .status
        .success());
    let v = env.json(&["run", "show", "probe-1"]);
    assert_eq!(v["ledger"]["path"], ledger.as_str());
    assert_eq!(v["outcome"]["accepted"], 2);
    assert_eq!(v["kos_finding"], "finding-9");
    for (flag, field) in [
        ("--kind", "kind"),
        ("--factory", "factory"),
        ("--factory-ref", "factory_ref"),
        ("--arm", "arm"),
        ("--run-id", "run_id"),
        ("--block", "block"),
        ("--order", "order"),
        ("--protocol-role", "protocol_role"),
        ("--split", "split"),
        ("--protocol-sha", "protocol_sha"),
        ("--harness-build", "harness_build"),
        ("--new-id", "id"),
    ] {
        let out = env.critic(&["run", "update", "probe-1", flag, "x"]);
        assert_eq!(out.status.code(), Some(1), "{flag}: {}", text(&out));
        assert!(
            text(&out).contains("P3") && text(&out).contains(field),
            "{flag}: {}",
            text(&out)
        );
    }
    let outside = env.dir.path().join("o.json");
    std::fs::write(&outside, "{}").unwrap();
    assert_eq!(
        env.critic(&[
            "run",
            "update",
            "probe-1",
            "--cost",
            outside.to_str().unwrap()
        ])
        .status
        .code(),
        Some(1)
    );
    assert_eq!(
        env.json(&["run", "show", "probe-1"])["arm"],
        "one-session",
        "identity fields are unchanged"
    );
}

#[test]
fn isolation_names_each_recipe_line_that_reads_run_and_passes_a_clean_justfile() {
    // No store needed: the verb parses a justfile.
    let bin = env!("CARGO_BIN_EXE_critic");
    let clean = std::process::Command::new(bin)
        .args(["doctor", "isolation", "--orc"])
        .arg(fixture("justfile.clean"))
        .output()
        .unwrap();
    assert_eq!(clean.status.code(), Some(0), "{}", text(&clean));
    assert!(text(&clean).contains("isolation holds"));
    let dirty = std::process::Command::new(bin)
        .args(["doctor", "isolation", "--orc"])
        .arg(fixture("justfile.dirty"))
        .output()
        .unwrap();
    assert_eq!(dirty.status.code(), Some(1), "{}", text(&dirty));
    let t = text(&dirty);
    assert!(
        t.contains("recipe legion-list reads run/") && t.contains(":8:"),
        "{t}"
    );
    assert!(
        t.contains("recipe sweep reads run/") && t.contains(":12:"),
        "{t}"
    );
    assert!(!t.contains("recipe status"), "{t}");
}
