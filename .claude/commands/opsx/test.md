---
name: "OPSX: Self-test"
description: Delegate the full pre-PR self-test to a subagent — pytest + regression + spec validation, with a tight pass/fail summary back to the main thread.
category: Workflow
tags: [workflow, testing]
---

You are running the diting self-test gate. The same four checks CI
will run on the PR — running them locally now means you catch
failures before pushing.

This command exists to keep test logs out of the parent context.
Delegate the run to a subagent (general-purpose Agent), wait for its
single-message report, then summarise pass/fail status back to the
user in 2-3 lines.

## Steps

1. **Identify the change you're testing.**

   - If `$ARGUMENTS` is non-empty, treat it as the change-name
     under `openspec/changes/<name>/` to validate explicitly.
   - If empty, scan `openspec/changes/` for an active (non-archive)
     change. If exactly one exists, use it. If zero, skip the
     active-change validation step (changes-only validation is
     a no-op without an active change). If more than one, ask
     the user which.

2. **Spawn an Agent with `subagent_type=general-purpose`.** Brief
   it like a smart colleague who just walked into the room:

   > Run diting's pre-PR self-test gate from the repo root.
   > Execute these four commands in order, capturing exit codes:
   >
   > ```
   > uv run pytest
   > uv run python scripts/tui_snapshot.py --mode regression
   > openspec validate --specs --strict
   > openspec validate <CHANGE_NAME> --strict   # only if a change is active
   > ```
   >
   > Report back with:
   > - PASS / FAIL for each gate
   > - For FAILs only, the smallest excerpt of output that explains
   >   why (a stack trace's last frame, the failing assertion line,
   >   the spec validator's error path).
   > - Total wall time in seconds.
   >
   > Do NOT fix anything; do NOT keep going if a gate fails — report
   > the failure and stop. Under 200 words.

3. **Read the agent's report.** It will return one message back.

4. **Summarise to the user**:

   - If all gates pass: ONE line, `4/4 gates pass (Xs)`.
   - If anything fails: list the failed gate(s) and quote the agent's
     "why" excerpt verbatim. Do NOT speculate on the fix; the user
     reads the failure and decides next steps.

5. **Don't propose fixes.** This command's contract is "tell me
   the state", not "patch the code". The user runs `/opsx:test`
   again after each fix attempt.

## Notes

- The four gates match CI exactly — see `.github/workflows/test.yml`.
- Real-environment scenarios (`scripts/tui_snapshot.py --mode explore`)
  are NOT in this gate; those are the `/tui-audit` skill's territory.
- If the agent times out (long pytest run), the slash command
  surfaces the timeout instead of guessing.
