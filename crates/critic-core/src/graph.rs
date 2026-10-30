//! Lineage graph rules over (child, parent) pairs. An edge says the child's
//! starting state came from the parent's, so a cycle is a run that derives from
//! itself.

use std::collections::{HashMap, HashSet};

/// True when adding `child -> parent` to `edges` would close a cycle.
pub fn would_cycle(edges: &[(String, String)], child: &str, parent: &str) -> bool {
    if child == parent {
        return true;
    }
    let mut up: HashMap<&str, Vec<&str>> = HashMap::new();
    for (c, p) in edges {
        up.entry(c.as_str()).or_default().push(p.as_str());
    }
    // The new edge closes a cycle when `child` is already an ancestor of `parent`.
    let mut seen: HashSet<&str> = HashSet::new();
    let mut stack = vec![parent];
    while let Some(n) = stack.pop() {
        if n == child {
            return true;
        }
        if !seen.insert(n) {
            continue;
        }
        if let Some(ps) = up.get(n) {
            stack.extend(ps.iter().copied());
        }
    }
    false
}

/// Walk from `start` along `edges` (child -> parent). With `ancestors` true it
/// follows parents; otherwise it follows children. Returns ids in breadth-first
/// order, each once, `start` excluded.
pub fn walk(edges: &[(String, String)], start: &str, ancestors: bool) -> Vec<String> {
    let mut next: HashMap<&str, Vec<&str>> = HashMap::new();
    for (c, p) in edges {
        let (from, to) = if ancestors {
            (c.as_str(), p.as_str())
        } else {
            (p.as_str(), c.as_str())
        };
        next.entry(from).or_default().push(to);
    }
    for v in next.values_mut() {
        v.sort_unstable();
    }
    let mut out = Vec::new();
    let mut seen: HashSet<&str> = HashSet::from([start]);
    let mut queue = std::collections::VecDeque::from([start]);
    while let Some(n) = queue.pop_front() {
        if let Some(ns) = next.get(n) {
            for m in ns {
                if seen.insert(m) {
                    out.push((*m).to_string());
                    queue.push_back(m);
                }
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn e(c: &str, p: &str) -> (String, String) {
        (c.to_string(), p.to_string())
    }

    #[test]
    fn self_edge_is_a_cycle() {
        assert!(would_cycle(&[], "a", "a"));
    }

    #[test]
    fn closing_a_chain_is_a_cycle_and_extending_it_is_not() {
        let edges = vec![e("b", "a"), e("c", "b")];
        assert!(
            would_cycle(&edges, "a", "c"),
            "a derived from c, which derives from b, from a"
        );
        assert!(!would_cycle(&edges, "d", "c"));
        assert!(
            !would_cycle(&edges, "c", "a"),
            "a second path down is not a cycle"
        );
    }

    #[test]
    fn walk_follows_both_directions_without_repeats() {
        let edges = vec![e("b", "a"), e("c", "a"), e("d", "b"), e("d", "c")];
        assert_eq!(walk(&edges, "d", true), vec!["b", "c", "a"]);
        assert_eq!(walk(&edges, "a", false), vec!["b", "c", "d"]);
    }
}
