//! The critic run record: one id per run, its sessions, its append-only lineage,
//! and the pointers (path plus sha256) to derived outputs. Design:
//! `docs/design/critic-mvp.md` sections 3, 4 and 6 item 1.

pub mod config;
pub mod doctor;
pub mod error;
pub mod graph;
pub mod model;
pub mod paths;
pub mod store;

pub use error::{Error, Refusal};
