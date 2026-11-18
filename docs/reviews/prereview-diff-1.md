# Goldfish review: bin/prereview (diffs 1-3)

- Branch: feat/prereview. Reviewer: goldfish (fresh agent), read-only.
- Purpose: run G8/G9's reviewer panel on a hand-built case before launch, on subscription lanes (founder 2026-11-18).

## Diff 1: FAIL
1. BLOCKER: reviewers loaded the user's personal OpenCode/Codex configs (remote MCP servers, plugins), so case material could reach outside services. **Fixed:** isolated as factory/model_runtime.py runs them. Logs of the first runs (stopped) showed MCP servers connecting at startup but no tool call.
2. SHOULD: Codex settings differed (effort, web search, network). **Fixed:** effort high, web_search disabled, workspace-write with network on.
3. SHOULD: bench defaulted to the working checkout. **Fixed:** `--bench` required; commit and dirty flag recorded.
4. SHOULD: symlinks kept. **Fixed:** followed, as the factory's copy.
5. SHOULD: timeout left children; a missing CLI crashed the run. **Fixed:** process group killed; errors kept per sample.
6-8. NITs (--out checks, --samples 0, dict findings). **Fixed.**

## Diff 2: FAIL
1. BLOCKER: copying `~/.codex/auth.json` whole let a sample rotate the refresh token and log the user out. **Fixed:** factory `codex_login.worker_auth` (external-token mode, no refresh token).
2. SHOULD: home folder and credentials reachable. **Fixed:** env allowlist, HOME=scratch, OPENCODE_DISABLE_CLAUDE_CODE.
3. SHOULD: no small_model. **Fixed:** pinned, only the Go provider enabled, --title.
4-6. **Fixed** (errors inside try, killpg in finally, --out inside case, non-git bench). `opencode run --standalone` added: the shared background service carries the user's config.

## Diff 3: PASS
NITs fixed: token validated for the whole timeout; CLI versions recorded; import at module top; run-count defaults commented.
Known differences from the gate (in the docstring and findings.md): no built bench images, Codex sandboxed rather than unsandboxed, no founder ruling, local Codex 0.167.2 vs the factory's pinned 0.162.1.

## Diff 4 (`--reviewers`, Codex-only default): PASS
SHOULDs fixed: duplicate/whitespace reviewer names deduped and stripped; CLI versions recorded only for the CLIs used, and a missing CLI no longer loses summary.json. NITs fixed: dead empty check dropped, usage and docstring say the default is the Codex half of the panel.
