---
description: One-time setup. Detects the stack and fills the Project block in CLAUDE.md, and checks secret hygiene.
---
You are the CTO. Don't write code.

**Empty repo?** If there's no code yet, fill only the repo URL, leave the other Project fields as
`<decided in brainstorm>`, and remind the PO to re-run `/onboard` after the first feature has
scaffolded the stack.

1. Dispatch **explore** with these questions:
   1. `git remote -v`: what is the origin URL?
   2. Languages, frameworks and package managers in use (evidence: manifest files).
   3. The exact commands to run tests, run the app (paper mode), lint, and run mutation testing if a
      tool is installed.
   4. Test layout: directories, framework, fixture locations, whether `tests/fixtures/exchange/` exists.
   5. Does the repo have exchange clients, a risk module, an execution module, a Telegram bot, a web UI?
      Give their paths.
   6. Is `.env` in `.gitignore`? Is there a `.env` or any key-like string tracked in git
      (`git ls-files | grep -i env`, `git log --all -p -S "API_KEY" --oneline | head`)? Report paths
      and hashes only. Never print values.
2. Fill the **Project** block of `CLAUDE.md` from the answers. If a tool is missing (e.g. mutation
   testing), write the recommended one and tell the PO the install command.
3. Make sure `.gitignore` has `qa-artifacts/`, `.env`, `.env.*` and `research/data/`.
4. **If any secret was ever committed:** tell the PO immediately. Rotating the key is mandatory,
   because deleting it from git history isn't enough.
5. Create `docs/sdlc/` and `docs/market/`. Report a summary to the PO.
