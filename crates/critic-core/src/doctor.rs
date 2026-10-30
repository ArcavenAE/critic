//! `critic doctor isolation`: the Q10 check that no recipe in the orchestrator's
//! justfile reads `run/`, where the tier-3 run repos live. The verb parses the
//! justfile it is given; it never needs the orchestrator checkout in CI.

/// One reference to `run/`: the justfile line, the recipe it sits in (or `-` at
/// top level) and the line's text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunRef {
    pub line: usize,
    pub recipe: String,
    pub text: String,
}

/// True when `s` names the `run/` directory: `run/` at the start of a word, or
/// behind `./` or `../`, and not the tail of a longer path such as `/var/run/x`
/// or `verify-run/`.
fn names_run_dir(s: &str) -> bool {
    let b = s.as_bytes();
    let mut i = 0;
    while let Some(off) = s[i..].find("run/") {
        let at = i + off;
        i = at + 1;
        // Walk back over any `./` and `../` prefixes to the character before the path.
        let mut start = at;
        loop {
            if s[..start].ends_with("../") {
                start -= 3;
            } else if s[..start].ends_with("./") {
                start -= 2;
            } else {
                break;
            }
        }
        let before = if start == 0 {
            None
        } else {
            Some(b[start - 1] as char)
        };
        let word_start = match before {
            None => true,
            Some(c) => {
                c.is_whitespace()
                    || matches!(
                        c,
                        '"' | '\''
                            | '`'
                            | '='
                            | '('
                            | ':'
                            | ','
                            | '{'
                            | '['
                            | '<'
                            | '>'
                            | '|'
                            | ';'
                    )
            }
        };
        if word_start {
            return true;
        }
    }
    false
}

/// Every line of `justfile` that references `run/`. A line starting with `#` is
/// a comment and is skipped.
pub fn run_references(justfile: &str) -> Vec<RunRef> {
    let mut recipe = "-".to_string();
    let mut out = Vec::new();
    for (n, line) in justfile.lines().enumerate() {
        let trimmed = line.trim_start();
        let indented = line.starts_with(' ') || line.starts_with('\t');
        if !indented && !trimmed.is_empty() && !trimmed.starts_with('#') {
            // `name arg: dep` is a recipe header; `set ...` and `x := y` are not.
            if let Some((head, _)) = trimmed.split_once(':') {
                if !trimmed.contains(":=")
                    && !trimmed.starts_with("set ")
                    && !trimmed.starts_with("import ")
                {
                    recipe = head
                        .split_whitespace()
                        .next()
                        .unwrap_or("-")
                        .trim_start_matches('@')
                        .to_string();
                }
            }
        }
        if trimmed.starts_with('#') {
            continue;
        }
        if names_run_dir(line) {
            out.push(RunRef {
                line: n + 1,
                recipe: recipe.clone(),
                text: line.trim().to_string(),
            });
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_run_directory_is_found_in_the_usual_spellings() {
        for hit in [
            "ls run/*",
            "for d in run/*/; do",
            "cd ./run/x",
            "cat ../run/x",
            "x=\"run/\"",
            "(run/a)",
        ] {
            assert!(names_run_dir(hit), "{hit}");
        }
    }

    #[test]
    fn other_paths_that_end_in_run_are_not_the_run_directory() {
        for miss in [
            "ls /var/run/x",
            "verify-run/x",
            "tests/run/x",
            "prerun/x",
            "echo running",
        ] {
            assert!(!names_run_dir(miss), "{miss}");
        }
    }

    #[test]
    fn a_reference_is_attributed_to_its_recipe_and_comments_are_skipped() {
        let j = "set shell := [\"bash\", \"-c\"]\n# run/ is private\nstatus:\n    git status\nbuild-all:\n    ls run/*\n    echo done\n";
        let refs = run_references(j);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].recipe, "build-all");
        assert_eq!(refs[0].line, 6);
    }
}
