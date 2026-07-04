# Task Tracking (beads/bd)

## What bd tracks

Work items — tasks, subtasks, blockers, "what's next."

## Quick commands

```sh
bd ready               # unblocked work — run at session start
bd list --status open  # all open tasks
bd show <id>           # task details
bd create --title "..." --type task  # create a task
bd close <id>          # close a completed task
```

## Cross-subrepo access

bd is initialized at the orchestrator root. This subrepo has a symlink:
`.beads -> ../.beads`. bd commands work from this directory.

## Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference
- Use `bd remember` for persistent knowledge
