CREATE TABLE runs (
  id VARCHAR(128) NOT NULL,
  kind VARCHAR(16) NOT NULL,
  factory VARCHAR(255) NULL,
  factory_ref JSON NULL,
  arm VARCHAR(255) NULL,
  run_id VARCHAR(255) NULL,
  block INT NULL,
  run_order INT NULL,
  protocol_role VARCHAR(32) NULL,
  split VARCHAR(16) NULL,
  protocol_sha VARCHAR(128) NULL,
  harness_build VARCHAR(255) NULL,
  locus JSON NULL,
  transcript_roots JSON NULL,
  started_at VARCHAR(40) NULL,
  ended_at VARCHAR(40) NULL,
  status VARCHAR(16) NOT NULL,
  run_state VARCHAR(16) NULL,
  void_rule VARCHAR(255) NULL,
  host_class VARCHAR(64) NULL,
  outcome JSON NULL,
  metrics JSON NULL,
  kos_finding VARCHAR(255) NULL,
  ledger_path VARCHAR(1024) NULL,
  ledger_sha256 CHAR(64) NULL,
  cost_path VARCHAR(1024) NULL,
  cost_sha256 CHAR(64) NULL,
  registered_at VARCHAR(40) NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT runs_kind CHECK (kind IN ('legion','spike','fork','trial')),
  CONSTRAINT runs_split CHECK (split IS NULL OR split IN ('search','validation','test')),
  CONSTRAINT runs_state CHECK (run_state IS NULL OR run_state IN ('started','completed','stalled','crashed','timed-out','limit-stopped','void')),
  CONSTRAINT runs_status CHECK (status IN ('active','archived','abandoned')),
  CONSTRAINT runs_void CHECK ((run_state = 'void' AND void_rule IS NOT NULL AND void_rule <> '') OR ((run_state IS NULL OR run_state <> 'void') AND void_rule IS NULL)),
  CONSTRAINT runs_ledger_pair CHECK ((ledger_path IS NULL AND ledger_sha256 IS NULL) OR (ledger_path IS NOT NULL AND ledger_sha256 IS NOT NULL)),
  CONSTRAINT runs_cost_pair CHECK ((cost_path IS NULL AND cost_sha256 IS NULL) OR (cost_path IS NOT NULL AND cost_sha256 IS NOT NULL))
);
CREATE TABLE run_sessions (
  run_id_fk VARCHAR(128) NOT NULL,
  harness VARCHAR(64) NOT NULL,
  harness_session_id VARCHAR(255) NOT NULL,
  marvel_session_key VARCHAR(255) NULL,
  stamp_workspace VARCHAR(128) NULL,
  stamp_team VARCHAR(128) NULL,
  stamp_role VARCHAR(128) NULL,
  stamp_seat VARCHAR(128) NULL,
  stamp_cluster VARCHAR(128) NULL,
  stamp_prompt_hash VARCHAR(128) NULL,
  PRIMARY KEY (run_id_fk, harness, harness_session_id),
  CONSTRAINT run_sessions_run FOREIGN KEY (run_id_fk) REFERENCES runs (id)
);
CREATE TABLE lineage_edges (
  edge_id BIGINT NOT NULL AUTO_INCREMENT,
  child VARCHAR(128) NOT NULL,
  parent VARCHAR(128) NOT NULL,
  kind VARCHAR(16) NOT NULL,
  recorded_at VARCHAR(40) NOT NULL,
  recorded_by VARCHAR(128) NOT NULL,
  PRIMARY KEY (edge_id),
  CONSTRAINT lineage_edges_child FOREIGN KEY (child) REFERENCES runs (id),
  CONSTRAINT lineage_edges_parent FOREIGN KEY (parent) REFERENCES runs (id),
  CONSTRAINT lineage_edges_kind CHECK (kind IN ('derived-from','resumed-from')),
  CONSTRAINT lineage_edges_distinct CHECK (child <> parent)
);
CREATE TABLE lineage_corrections (
  correction_id BIGINT NOT NULL AUTO_INCREMENT,
  supersedes BIGINT NOT NULL,
  replacement_edge_id BIGINT NULL,
  reason VARCHAR(1024) NOT NULL,
  recorded_at VARCHAR(40) NOT NULL,
  recorded_by VARCHAR(128) NOT NULL,
  PRIMARY KEY (correction_id),
  CONSTRAINT lineage_corrections_edge FOREIGN KEY (supersedes) REFERENCES lineage_edges (edge_id),
  CONSTRAINT lineage_corrections_replacement FOREIGN KEY (replacement_edge_id) REFERENCES lineage_edges (edge_id),
  CONSTRAINT lineage_corrections_reason CHECK (reason <> '')
);
-- Dolt triggers do not support SIGNAL, so the append-only rule is a guard table: an
-- UPDATE or DELETE on either lineage table runs a trigger that inserts NULL into a
-- NOT NULL column, which fails the statement and leaves every row as it was. The
-- column name is the message the refusal prints.
CREATE TABLE lineage_guard (lineage_is_append_only_edit_refused VARCHAR(8) NOT NULL);
CREATE TRIGGER lineage_edges_no_update BEFORE UPDATE ON lineage_edges FOR EACH ROW INSERT INTO lineage_guard (lineage_is_append_only_edit_refused) VALUES (NULL);
CREATE TRIGGER lineage_edges_no_delete BEFORE DELETE ON lineage_edges FOR EACH ROW INSERT INTO lineage_guard (lineage_is_append_only_edit_refused) VALUES (NULL);
CREATE TRIGGER lineage_corrections_no_update BEFORE UPDATE ON lineage_corrections FOR EACH ROW INSERT INTO lineage_guard (lineage_is_append_only_edit_refused) VALUES (NULL);
CREATE TRIGGER lineage_corrections_no_delete BEFORE DELETE ON lineage_corrections FOR EACH ROW INSERT INTO lineage_guard (lineage_is_append_only_edit_refused) VALUES (NULL);
CREATE VIEW effective_lineage AS
  SELECT e.edge_id AS edge_id, e.child AS child, e.parent AS parent, e.kind AS kind
    FROM lineage_edges e
   WHERE NOT EXISTS (SELECT 1 FROM lineage_corrections c WHERE c.supersedes = e.edge_id);
