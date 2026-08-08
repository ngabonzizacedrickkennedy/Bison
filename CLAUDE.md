# BISON — Working Rules for Claude

## Rule 1 — Never run terminal commands

Do **not** run any terminal or shell command in this repository. No exceptions.

This includes, and is not limited to:

- `pnpm` / `npm` / `npx` / `corepack` — no `install`, `build`, `run`, `add`
- `tsc`, `tsx`, `turbo`, `vite`, or any build, generate, or codegen command
- `pytest`, `python`, `uv`, `pip`, or any test or script runner
- `git` — no `status`, `add`, `commit`, `push`, `log`, `diff`
- `ls`, `cat`, `grep`, `find`, or any other inspection command

Do not verify, build, install, test, lint, or typecheck. Do not check whether
something worked. If verification is wanted, it will be asked for explicitly.

## Rule 2 — Apply the given code exactly

When code is provided, write it to the named file **verbatim**.

- Do not add lines, comments, imports, exports, types, or helpers.
- Do not remove or reorder anything.
- Do not rename, reformat, or "clean up".
- Do not refactor, optimize, or improve.
- Do not create, edit, or delete any file that was not named.
- Do not fix what looks like a bug. Write it as given.

The code is specified deliberately. It is not a draft to be reviewed, and it is
not an invitation to redesign. Treat it as final.

## Rule 3 — Do exactly the stated scope

Do only what was asked, for only the files named. Nothing else.

Do not anticipate the next step. Do not prepare for it. Do not add configuration,
scaffolding, or dependencies "so it will work later".

## Rule 4 — Observations go in the reply, never in the code

If something looks wrong, say it in the chat reply as plain text, after the code
has been written as given. Never express a concern by changing the code, and
never change the code and then mention it.

Keep such notes short. One or two sentences. Then stop.
