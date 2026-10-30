//! Runtime paths stay under the runtime root, outside the repo (P7, charter B2).

use crate::error::Refusal;
use sha2::{Digest, Sha256};
use std::path::{Component, Path, PathBuf};

/// Resolve `.` and `..` without touching the disk.
fn lexical(p: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in p.components() {
        match c {
            Component::ParentDir => {
                out.pop();
            }
            Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// The path with symlinks resolved as far as the disk allows: the longest
/// existing prefix is canonicalised and the rest is appended lexically.
fn resolved(p: &Path) -> PathBuf {
    let p = lexical(p);
    let mut tail = Vec::new();
    let mut cur = p.as_path();
    loop {
        if let Ok(c) = cur.canonicalize() {
            let mut out = c;
            for t in tail.iter().rev() {
                out.push(t);
            }
            return out;
        }
        match (cur.parent(), cur.file_name()) {
            (Some(parent), Some(name)) => {
                tail.push(name.to_os_string());
                cur = parent;
            }
            _ => return p,
        }
    }
}

/// R-g. `path` must be absolute and, after resolving `..` and symlinks, inside `root`.
pub fn require_under(root: &Path, field: &str, path: &str) -> Result<PathBuf, Refusal> {
    let p = Path::new(path);
    if !p.is_absolute() {
        return Err(Refusal::new(
            "R-g",
            field,
            format!("{path} is not an absolute path under the runtime root"),
        ));
    }
    let r = resolved(p);
    if !r.starts_with(resolved(root)) {
        return Err(Refusal::new(
            "R-g",
            field,
            format!("{path} is outside the runtime root"),
        ));
    }
    Ok(r)
}

/// R-g. The runtime root must not sit inside any git checkout, so runtime data
/// cannot be committed by accident.
pub fn runtime_root_outside_git(root: &Path) -> Result<(), Refusal> {
    let r = resolved(root);
    for a in r.ancestors() {
        if a.join(".git").exists() {
            return Err(Refusal::new(
                "R-g",
                "runtime_root",
                format!(
                    "{} sits inside the git checkout at {}",
                    root.display(),
                    a.display()
                ),
            ));
        }
    }
    Ok(())
}

/// A derived output stored by path and sha256 (P1). The file must sit under the
/// runtime root (R-g); it is read for its hash and never parsed.
pub fn pointer(
    root: &Path,
    field: &str,
    path: &str,
) -> Result<crate::model::FilePointer, crate::error::Error> {
    let resolved_path = require_under(root, field, path)?;
    let sha256 = sha256_file(&resolved_path)
        .map_err(|e| crate::error::Error::other(format!("{field}: cannot read {path}: {e}")))?;
    Ok(crate::model::FilePointer {
        path: path.to_string(),
        sha256,
    })
}

/// The sha256 of a file, as lowercase hex.
pub fn sha256_file(path: &Path) -> std::io::Result<String> {
    let bytes = std::fs::read(path)?;
    Ok(Sha256::digest(&bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dotdot_cannot_climb_out_of_the_root() {
        let root = tempfile::tempdir().unwrap();
        let r = root.path();
        let inside = format!("{}/a/b.json", r.display());
        let outside = format!("{}/a/../../elsewhere.json", r.display());
        assert!(require_under(r, "ledger", &inside).is_ok());
        assert_eq!(
            require_under(r, "ledger", &outside).unwrap_err().rule,
            "R-g"
        );
        assert!(require_under(r, "ledger", "relative/path").is_err());
    }

    #[test]
    fn a_symlink_out_of_the_root_is_refused() {
        let root = tempfile::tempdir().unwrap();
        let other = tempfile::tempdir().unwrap();
        std::os::unix::fs::symlink(other.path(), root.path().join("link")).unwrap();
        let p = format!("{}/link/x.json", root.path().display());
        assert!(require_under(root.path(), "cost", &p).is_err());
    }

    #[test]
    fn a_root_inside_a_checkout_is_refused() {
        let repo = tempfile::tempdir().unwrap();
        std::fs::create_dir(repo.path().join(".git")).unwrap();
        let inner = repo.path().join("runtime");
        std::fs::create_dir(&inner).unwrap();
        assert!(runtime_root_outside_git(&inner).is_err());
        let clean = tempfile::tempdir().unwrap();
        assert!(runtime_root_outside_git(clean.path()).is_ok());
    }
}
