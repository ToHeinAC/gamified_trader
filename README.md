# Gamified Trader

Ein gamifiziertes Trading-Lernspiel mit historischen Kursdaten. Built with Claude Code and
reviewed by a second tool such as Codex; see [PRD.md](PRD.md) for what and why.

This repo started from a template (below is its own setup story) whose rules and quality gate
still apply as-is.

## Use it

1. `uv sync && uv run pre-commit install`
2. `uv run pre-commit run --all-files` should pass.
3. Start `claude` in the repo. It loads `CLAUDE.md`, which imports `AGENTS.md` and `IMPLEMENTATION.md`.

Requirements: [uv](https://docs.astral.sh/uv/) and git. uv installs Python itself.

## Usage (M1: Kursdaten)

```bash
uv run gt data download                 # full universe (src/app/resources/universe.csv)
uv run gt data download --tickers AAPL  # a subset
uv run gt data update                   # append new days, reload on split/dividend re-adjustment
```

Config via environment (`.env`, see `.env.example`): `GT_DATA_DIR` (default `data/`),
`GT_YAHOO_PAUSE_S` (default `2.0`, pause between Yahoo batches). Details: [docs/data.md](docs/data.md).

## Layout

```
AGENTS.md            rules for every AI coding tool (Claude Code via CLAUDE.md, Codex natively)
CLAUDE.md            imports AGENTS.md and IMPLEMENTATION.md
PRD.md               what and why (template)
IMPLEMENTATION.md    current state: phase table, module map, run/verify
docs/                deep docs per component; architecture.md
src/app/             code
tests/               pytest suite (offline) and the repo rule checks
.claude/settings.json      shared permissions and hooks
.claude/hooks/             hook scripts (tested in tests/)
.claude/commands/          /commit-git, /documentation-update
.pre-commit-config.yaml    the quality gate
.github/workflows/ci.yml   runs the gate on Python 3.11 and 3.14
```

## Where each rule is enforced

| Rule | Edit hook | Stop hook | Commit | CI |
|---|---|---|---|---|
| Formatting (ruff) | yes | yes | yes | yes |
| Lint, complexity ≤ 10 (ruff); types (pyright) | | yes | yes | yes |
| Tests, branch coverage ≥ 85 %, suite ≤ 60 s | | yes | yes | yes |
| Functions ≤ 50 lines; doc size limits and links | | yes | yes | yes |
| No `.env` files, no private keys | | yes | yes | yes |
| Secret scan of staged changes (gitleaks) | | | yes | |

The Stop hook runs only when `.py` files changed. The process rules (red-green, small commits,
docs updates) live in [AGENTS.md](AGENTS.md) §5.3, and the review checks them.
Details: [docs/architecture.md](docs/architecture.md).

## Skills and commands

In this repository (every clone gets them):

- `/commit-git`: small Conventional Commits through the gate. Only you can invoke it, and it never pushes without asking.
- `/documentation-update`: brings the docs in line with the code since the last commit.

Not in this repository:

- `first-principles-mindmap` (writes `MINDMAP.md`) and `prd-from-mindmap` (writes `PRD.md`) are
  personal skills in the author's claude.ai account (Customize > Skills). Other users can upload
  their own, or fill in `PRD.md` by hand; its headings are the contract.
- Claude Code built-ins such as `/code-review`, `/security-review` and `/simplify` need no setup.

## Credits and license

AGENTS.md §1–4 come from
[andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) (MIT), see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Everything else: Apache-2.0, see [LICENSE](LICENSE).
