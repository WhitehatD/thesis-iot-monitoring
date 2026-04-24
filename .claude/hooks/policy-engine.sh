#!/bin/bash
# rtk-hook-version: 1
# policy-engine.sh — PreToolUse hook for Bash (runs BEFORE sandbox-guard.sh)
# Context-aware policy layer: allow/warn/gate/block based on branch, path, pattern.
# Reads rules from .claude/policies.json. First matching rule wins.

# Skip all checks in claudex autonomous mode
[ -n "$CLAUDEX" ] && exit 0

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$COMMAND" ] && exit 0

# Strip single-quoted strings to avoid false positives on data payloads
CHECK=$(echo "$COMMAND" | sed "s/'[^']*'/''/g")

# Resolve policy file and project root
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
POLICY_FILE="${PROJECT_ROOT}/.claude/policies.json"
[ ! -f "$POLICY_FILE" ] && exit 0

# Cache branch name (one git call per invocation)
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

# Evaluate a single condition object against current context
# Returns 0 (true) if condition is met, 1 (false) if not
eval_condition() {
  local cond="$1"
  [ -z "$cond" ] || [ "$cond" = "null" ] && return 0

  # branch: regex match against current branch
  local branch_pat
  branch_pat=$(echo "$cond" | jq -r '.branch // empty')
  if [ -n "$branch_pat" ]; then
    echo "$BRANCH" | grep -qE "^($branch_pat)$" || return 1
  fi

  # path_outside_project: check if any absolute path in command is outside project
  local outside
  outside=$(echo "$cond" | jq -r '.path_outside_project // empty')
  if [ "$outside" = "true" ] && [ -n "$PROJECT_ROOT" ]; then
    local found_outside=false
    for p in $(echo "$CHECK" | grep -oE '(/[a-zA-Z][a-zA-Z0-9_./-]+|[A-Z]:\\[^ ]+)'); do
      case "$p" in /dev/null|/tmp/*|-*) continue ;; esac
      [[ "$p" != "$PROJECT_ROOT"* ]] && found_outside=true && break
    done
    $found_outside || return 1
  fi

  # path: glob match against paths in the command
  local path_pat
  path_pat=$(echo "$cond" | jq -r '.path // empty')
  if [ -n "$path_pat" ]; then
    local path_matched=false
    for p in $(echo "$CHECK" | grep -oE '(/[a-zA-Z][a-zA-Z0-9_./-]+|[A-Z]:\\[^ ]+)'); do
      # shellcheck disable=SC2254
      case "$p" in $path_pat) path_matched=true; break ;; esac
    done
    $path_matched || return 1
  fi

  # not_namespace: for kubectl, check -n/--namespace flag is NOT in the list
  local ns_pat
  ns_pat=$(echo "$cond" | jq -r '.not_namespace // empty')
  if [ -n "$ns_pat" ]; then
    local ns
    ns=$(echo "$CHECK" | grep -oP '(-n|--namespace)[= ]\K[a-zA-Z0-9_-]+' | head -1)
    [ -z "$ns" ] && ns="default"
    echo "$ns" | grep -qE "^($ns_pat)$" && return 1
  fi

  return 0
}

# Read rule count once
RULE_COUNT=$(jq '.rules | length' "$POLICY_FILE" 2>/dev/null)
[ -z "$RULE_COUNT" ] || [ "$RULE_COUNT" -eq 0 ] && exit 0

# Evaluate rules top-to-bottom, first match wins
for (( i=0; i<RULE_COUNT; i++ )); do
  RULE=$(jq -c ".rules[$i]" "$POLICY_FILE")
  PATTERN=$(echo "$RULE" | jq -r '.match')
  echo "$CHECK" | grep -qE "$PATTERN" || continue

  CONDITION=$(echo "$RULE" | jq -c '.condition // empty')
  eval_condition "$CONDITION" || continue

  ACTION=$(echo "$RULE" | jq -r '.action')
  MSG=$(echo "$RULE" | jq -r '.message // empty')
  RULE_ID=$(echo "$RULE" | jq -r '.id // "unknown"')

  case "$ACTION" in
    allow) exit 0 ;;
    warn)  [ -n "$MSG" ] && echo "POLICY WARNING [$RULE_ID]: $MSG" >&2; exit 0 ;;
    gate)  echo "POLICY GATE [$RULE_ID]: ${MSG:-Requires approval}"; exit 2 ;;
    block) echo "POLICY BLOCKED [$RULE_ID]: ${MSG:-Blocked by policy}"; exit 2 ;;
    pass)  exit 0 ;;
  esac
done

exit 0
