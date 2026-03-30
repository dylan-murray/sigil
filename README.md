<p align="center">
  <img alt="Sigil" src="assets/logo.svg" width="320">
</p>

<p align="center">
  <strong>Your codebase gets better every night. Automatically.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/badge/uv-package%20manager-de5fe9?style=flat-square&logo=astral&logoColor=white" alt="uv"></a>
  <a href="https://docs.litellm.ai/"><img src="https://img.shields.io/badge/LLM-100%2B%20models-ff6b6b?style=flat-square" alt="100+ LLM models"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green?style=flat-square" alt="Apache 2.0 License"></a>
  <a href="https://github.com/dylan-murray/sigil/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/dylan-murray/sigil/tests.yml?branch=main&style=flat-square&label=build" alt="Build"></a>
  <a href="https://github.com/dylan-murray/sigil/actions/workflows/codeql.yml"><img src="https://img.shields.io/github/actions/workflow/status/dylan-murray/sigil/codeql.yml?branch=main&style=flat-square&label=CodeQL" alt="CodeQL"></a>
  <a href="https://github.com/dylan-murray/sigil/actions/workflows/semgrep.yml"><img src="https://img.shields.io/github/actions/workflow/status/dylan-murray/sigil/semgrep.yml?branch=main&style=flat-square&label=Semgrep" alt="Semgrep"></a>
</p>

Sigil is an autonomous agent that watches your repo, finds improvements, and ships pull requests — while you sleep. Point it at a codebase, run it on a schedule, and wake up to small, safe PRs for bug fixes, refactors, and new features. Bigger ideas get filed as issues for you to review later.

**Get started in 2 minutes:** drop the [workflow file](examples/sigil.yml) into your repo, add an API key, and Sigil starts improving your codebase tonight. Bring any model — OpenAI, Anthropic, Gemini, DeepSeek, or any of 100+ providers supported by [LiteLLM](https://docs.litellm.ai/).

## 🤔 Why Sigil?

Every dev tool today is **reactive** — it waits for you to ask. Sigil is **proactive**.

While you're focused on feature work, Sigil is in the background catching the stuff that slips through the cracks: dead code nobody noticed, missing test coverage, type safety gaps, inconsistent patterns, and security issues. It doesn't just report problems — it fixes them and opens a PR. If a fix is too risky, it opens an issue instead.

**What you get after a run:**
- **Pull requests** for safe, low-risk improvements (bug fixes, dead code removal, type annotations, test gaps)
- **Issues** for higher-risk findings that need human review
- **Ideas** saved to `.sigil/ideas/` for future runs to pick up
- **Updated knowledge** so each run is smarter than the last

## ⚡ Quickstart

**Requirements:** Python 3.11+, [uv](https://github.com/astral-sh/uv), and an API key for your model provider.

```bash
# set your provider's API key
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY, etc.

uv tool install sigil
sigil init --repo .
sigil run --repo .             # or --dry-run to analyze without opening PRs
```

## 🔬 How It Works

Sigil runs an 8-stage async pipeline. Each stage can use a different model, so you can spend more on the hard steps and less on cheap ones.

```text
Discover → Learn → Connect MCP → Analyze + Ideate → Validate → Execute → Publish → Remember
```

| Stage | What happens |
|---|---|
| **Discover** | Scan repo structure, source files, and git history |
| **Learn** | Build or refresh `.sigil/memory/` knowledge files |
| **Connect MCP** | Load configured MCP servers and expose their tools to agents |
| **Analyze + Ideate** | Find fixable problems and generate improvement ideas (in parallel) |
| **Validate** | Triage candidates — reject weak or risky ones, assign dispositions |
| **Execute** | Apply approved work in isolated git worktrees, run pre/post hooks |
| **Publish** | Open pull requests and create GitHub issues |
| **Remember** | Update working memory so future runs have context |

## 🧩 Agents

Every pipeline stage is powered by a specialized agent. Mix and match models per agent — use a strong model for code generation and a fast one for memory compaction.

| Agent | What it does |
|---|---|
| **architect** | Plans the implementation approach for approved work items |
| **engineer** | Writes code in isolated worktrees, runs hooks |
| **auditor** | Finds concrete, fixable problems in the repo |
| **ideator** | Proposes feature ideas and improvement directions |
| **triager** | Reviews and ranks candidates, assigns dispositions (PR/issue/skip) |
| **challenger** | Second opinion on triager decisions (when `arbiter: true`) |
| **arbiter** | Resolves disagreements between triager and challenger |
| **reviewer** | Reviews code changes before commit |
| **compactor** | Turns discovery output into structured knowledge files |
| **memory** | Updates rolling working memory after each run |
| **selector** | Picks which knowledge files to load for a given task |
| **discovery** | Scans the repo for structure, files, and git history |

## 🛡️ Safety

- **Isolated execution** — code changes happen in git worktrees, never the main working tree
- **Pre/post hooks** — lint and test gates before and after code generation
- **Structured editing** — agents use structured tools, not freeform shell commands
- **Deduplication** — existing PRs and issues are checked before publishing
- **Convention-aware** — detects and follows `AGENTS.md`, `.cursorrules`, `CLAUDE.md`, and similar repo instructions
- **Rate-limited** — caps on PRs, issues, and ideas per run prevent spam
- **Budget cap** — hard limit on total spend per run (`max_spend_usd`)
- **Learns from mistakes** — previous attempts inform future runs

## 🎛️ Configuration

`sigil init` creates `.sigil/config.yml`. All fields are optional except `model`.

<details>
<summary>Full config reference</summary>

```yaml
model: anthropic/claude-sonnet-4-6       # default model for all agents

boldness: bold                            # conservative | balanced | bold | experimental
focus:                                    # what to look for
  - tests
  - dead_code
  - security
  - docs
  - types
  - features
  - refactoring

ignore:                                   # glob patterns to skip
  - "vendor/**"
  - "*.generated.*"

max_prs_per_run: 3                        # max PRs opened per run
max_github_issues: 5                      # max issues opened per run
max_ideas_per_run: 15                     # max ideas generated per run
idea_ttl_days: 180                        # auto-prune stale ideas
max_retries: 2                            # retries after post-hook failure
max_parallel_tasks: 3                     # max parallel worktrees
max_spend_usd: 20.0                       # hard cost cap per run

pre_hooks: []                             # run before code generation (failure aborts)
post_hooks: []                            # run after code generation (failure retries)

arbiter: false                            # enable parallel validation with challenger + arbiter

agents:                                   # per-agent model and iteration overrides
  engineer:
    model: anthropic/claude-opus-4-6
    max_iterations: 50
  auditor:
    model: google/gemini-2.5-flash
    max_iterations: 15
  compactor:
    model: anthropic/claude-haiku-4-5-20251001

mcp_servers:                              # external MCP tool servers
  - name: notion
    command: npx
    args: ["-y", "@notionhq/mcp-server"]
    env:
      NOTION_API_KEY: "${NOTION_API_KEY}"
    purpose: "product requirements and design docs"
  - name: snowflake
    url: "http://localhost:3001/sse"
    purpose: "data warehouse schemas and query results"
```

</details>

### 🎚️ Boldness Levels

| Level | Behavior |
|---|---|
| `conservative` | Obvious, low-risk fixes only |
| `balanced` | Safe refactors and common maintenance |
| `bold` | Broader cleanup, docs, and testing improvements |
| `experimental` | Speculative ideas and larger suggestions |

## 🔄 GitHub Action

Add Sigil to any repo with a single workflow file. It runs on a schedule and opens PRs automatically. See [`examples/sigil.yml`](examples/sigil.yml) for a copy-paste ready workflow.

```yaml
name: Sigil

on:
  schedule:
    - cron: '0 2 * * *'    # every night at 2am
  workflow_dispatch:

jobs:
  sigil:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      issues: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: dylan-murray/sigil@main
        # with:
        #   github-token: ${{ secrets.GITHUB_PAT_TOKEN }}  # optional: use a PAT so Sigil PRs trigger CI
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Sigil uses [LiteLLM](https://docs.litellm.ai/) — pass whichever API key your model provider needs via `env:`.

<details>
<summary>Action inputs</summary>

| Input | Default | Description |
|---|---|---|
| `github-token` | `github.token` | Token for git and PR operations. Pass a [PAT](https://github.com/settings/tokens) to trigger CI on Sigil PRs |
| `dry-run` | `false` | Passed as `--dry-run` |
| `sigil-version` | `sigil @ git+https://github.com/dylan-murray/sigil.git` | Package spec for `uv tool install` |

</details>

<details>
<summary>Required repo settings</summary>

1. **Settings → Actions → General → Workflow permissions** → select **"Read and write permissions"**
2. **Settings → Actions → General → Workflow permissions** → check **"Allow GitHub Actions to create and approve pull requests"**

</details>

## 📁 The `.sigil/` Directory

| Path | Committed | Purpose |
|---|---|---|
| `config.yml` | Yes | User-controlled configuration |
| `memory/` | Yes | Persistent repo knowledge maintained by Sigil |
| `ideas/` | Yes | Overflow ideas saved for later runs |
| `attempts.jsonl` | Yes | Execution history for learning from past runs |
| `worktrees/` | No | Temporary isolated execution sandboxes |
| `traces/` | No | LLM call traces (when `--trace` is used) |

## 📖 CLI Reference

```text
sigil init [OPTIONS]       Initialize a new Sigil project
sigil run [OPTIONS]        Run the full pipeline

Options:
  --repo, -r PATH          Repository path (default: .)
  --dry-run                Analyze only; no PRs or issues
  --trace                  Write LLM trace to .sigil/traces/last-run.json
  --refresh                Force a full knowledge rebuild
  --version, -v            Print version and exit
```

## 🛠️ Development

```bash
git clone https://github.com/dylan-murray/sigil.git
cd sigil
uv sync

uv run pytest tests/ -x -q
uv run ruff check .
uv run ruff format .
```

## License

Apache 2.0
