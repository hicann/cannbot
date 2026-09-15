---
name: workflow-orchestrator
description: Run a development workflow defined in workflow.yaml.
disable-model-invocation: true
---

# Workflow Orchestrator

`$SKILL_ROOT` = the absolute path of the directory containing this SKILL.md.

## Inputs

Four required inputs:

- `workflow.yaml` — path to the workflow definition file.
- `work_dir` — working directory; every workflow artifact and intermediate artifact is produced here.
- `provider` — the Coding Agent CLI used to execute the workflow's tasks.
- `prompt` — the prompt for this development task.

## Steps

1. **Collect inputs.** For any of the four that is missing, immediately call the question tool to ask the user; never guess or invent a default.
     Done when: all four are in hand.
2. **Absolutize paths.** Resolve `workflow.yaml` and `work_dir` with `realpath -m` (`-m` because `work_dir` may not exist yet).
   Done when: both are absolute.
3. **Run the orchestrator** (blackbox — see below) in a detached tmux session, logging output to `<work_dir>/orchestrator.log` with the exit status appended.

   Session name `<session>`: `orchestrator-<slug>`, where `<slug>` is the basename of `work_dir` with every character outside `[A-Za-z0-9_-]` replaced by `-`. If `tmux has-session -t <session>` says the name is taken, append `-2`, `-3`, … until it is free.

   ```bash
   tmux new-session -d -s <session> \
     'python3 $SKILL_ROOT/scripts/orchestrator.py \
       --yaml "<workflow.yaml>" \
       --work-dir "<work_dir>" \
       --provider "<provider>" \
       --prompt "<prompt>" > "<work_dir>/orchestrator.log" 2>&1; \
      echo "exit status: $?" >> "<work_dir>/orchestrator.log"'
   ```

   (Substitute `$SKILL_ROOT` and each `<...>` placeholder verbatim, **keeping the double quotes** — the inner shell parses the substituted command, and an unquoted prompt with spaces or `(` dies as a syntax error before the log redirect runs. Escape `"`, `` ` `` and `$` inside a substituted value.)

   Poll `tmux has-session -t <session>` (the same name chosen above) until it fails (session ended).
   Done when: the session has ended, and the log (output + exit status) has been relayed to the user verbatim.

## Blackbox rule

orchestrator.py is a blackbox: invoke it only through the command line above and judge it only by its output and exit code. Never read or edit its source.
