#!/usr/bin/env bash
# Blocks git commit / push while on main. Work happens on epic/* or feat/* branches.
# Exit code 2 = block the tool call and show stderr to the agent.
cmd=$(cat | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1)
case "$cmd" in
  *"git commit"*|*"git push"*) ;;
  *) exit 0 ;;
esac
branch=$(git -C "${CLAUDE_PROJECT_DIR:-.}" symbolic-ref --short HEAD 2>/dev/null)
if [ "$branch" = "main" ]; then
  echo "Blocked: never commit or push on main. Create an epic/<slug> or feat/<slug> branch and open a PR." >&2
  exit 2
fi
exit 0
