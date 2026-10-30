//! `$XDG_CONFIG_HOME/critic/config.toml` (or `--config`). Read by key; an
//! unknown key is an error. There is no default `dolt_url`: critic never writes
//! to a server it was not pointed at.

use crate::error::{Error, Result};
use serde::Deserialize;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DoltUrl {
    pub host: String,
    pub port: u16,
    pub user: String,
    /// The name of the environment variable that holds the password. The
    /// password itself never goes in the file.
    pub password_env: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub dolt_url: Option<DoltUrl>,
    pub runtime_root: Option<PathBuf>,
    #[serde(default)]
    pub host_classes: Vec<String>,
}

impl Config {
    pub fn parse(text: &str) -> Result<Config> {
        toml::from_str(text).map_err(|e| Error::other(format!("config: {e}")))
    }

    pub fn load(explicit: Option<&Path>) -> Result<Config> {
        let path = match explicit {
            Some(p) => p.to_path_buf(),
            None => default_path()?,
        };
        let text = std::fs::read_to_string(&path)
            .map_err(|e| Error::other(format!("config: cannot read {}: {e}", path.display())))?;
        Config::parse(&text)
    }

    pub fn dolt(&self) -> Result<&DoltUrl> {
        self.dolt_url.as_ref().ok_or_else(|| {
            Error::other(
                "config: dolt_url is not set; critic writes only to a server it was pointed at",
            )
        })
    }

    pub fn runtime_root(&self) -> Result<&Path> {
        self.runtime_root
            .as_deref()
            .ok_or_else(|| Error::other("config: runtime_root is not set"))
    }
}

fn default_path() -> Result<PathBuf> {
    if let Some(x) = std::env::var_os("XDG_CONFIG_HOME").filter(|v| !v.is_empty()) {
        return Ok(PathBuf::from(x).join("critic/config.toml"));
    }
    let home = std::env::var_os("HOME")
        .ok_or_else(|| Error::other("config: neither XDG_CONFIG_HOME nor HOME is set"))?;
    Ok(PathBuf::from(home).join(".config/critic/config.toml"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_unknown_key_is_an_error() {
        assert!(Config::parse("runtime_root = \"/x\"\nbogus = 1\n").is_err());
        assert!(Config::parse("[dolt_url]\nhost=\"h\"\nport=1\nuser=\"u\"\nextra=2\n").is_err());
    }

    #[test]
    fn an_unset_dolt_url_is_an_error_not_a_default() {
        let c = Config::parse("runtime_root = \"/x\"\n").unwrap();
        assert!(c.dolt().is_err());
    }

    #[test]
    fn the_password_is_named_by_variable_never_held() {
        let c = Config::parse(
            "[dolt_url]\nhost=\"h\"\nport=3306\nuser=\"u\"\npassword_env=\"CRITIC_PW\"\n",
        )
        .unwrap();
        assert_eq!(c.dolt().unwrap().password_env.as_deref(), Some("CRITIC_PW"));
        assert!(
            Config::parse("[dolt_url]\nhost=\"h\"\nport=3306\nuser=\"u\"\npassword=\"x\"\n")
                .is_err()
        );
    }
}
