# Repository

- GitHub: https://github.com/arthurmateus/tradestuff (`arthurmateus/tradestuff`)
- Default branch: `main`. All work lands here through pull requests.
- Branch scheme: `epic/<slug>` (long-lived, per epic), `feat/<slug>` (branches off its epic, merges back into it), `fix/<slug>`.
- Only one epic touches a given module at a time; that is what prevents merge conflicts. The CTO checks `docs/epics/*/design.md` "Touches" sections before starting a new epic.
- Agents are project-agnostic. Project-specific facts (repo, stack, domain) live in this file, `CLAUDE.md`, `docs/product/`, and the `trading-*` agents only.
