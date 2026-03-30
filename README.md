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

Bring any model — OpenAI, Anthropic, Gemini, DeepSeek, or any of 100+ providers supported by [LiteLLM](https://docs.litellm.ai/). Run locally or in GitHub Actions.

## 🤔 Why Sigil?

Every dev tool today is **reactive** — it waits for you to ask. Sigil is **proactive**.

While you're focused on feature work, Sigil is in the background catching the stuff that slips through the cracks: dead code nobody noticed, missing test coverage, type safety gaps, inconsistent patterns, and security issues. It doesn't just report problems — it fixes them and opens a PR. If a fix is too risky, it opens an issue instead.

**What you get after a run:**
- 🔧 **Pull requests** for safe, low-risk improvements (bug fixes, dead code removal, type annotations, test gaps)
- 📋 **Issues** for higher-risk findings that need human review
- 💡 **Ideas** saved to `.sigil/ideas/` for future runs to pick up
- 🧠 **Updated knowledge** so each run is smarter than the last

## ⚡ Quickstart

**Requirements:** Python 3.11+, [uv](https://github.com/astral-sh/uv), an API key for your model, and `GITHUB_TOKEN` for PR/issue creation.

```bash
uv tool install sigil

# first run creates .sigil/config.yml automatically
sigil run --repo .

# analyze only — no PRs or issues
sigil run --repo . --dry-run
```

Override the model at runtime:

```bash
sigil run --repo . --model openai/gpt-4o
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
| **Validate** | Review candidates — reject weak or risky ones |
| **Execute** | Apply approved work in isolated git worktrees, run lint and tests |
| **Publish** | Open pull requests and create GitHub issues |
| **Remember** | Update working memory so future runs have context |

## 🧩 Models and Agents

Every pipeline stage is powered by a specialized agent. Mix and match models per agent — use a strong model for code generation and a fast one for memory compaction.

| Agent | What it does |
|---|---|
| **compactor** | Turns discovery output into structured knowledge files |
| **analyzer** | Finds concrete, fixable problems in the repo |
| **ideator** | Proposes feature ideas and improvement directions |
| **validator** | Reviews and approves or rejects candidates |
| **codegen** | Applies changes in isolated worktrees and runs checks |
| **memory** | Updates rolling run memory |

When `validation_mode: parallel` is enabled, validation uses two independent reviewers plus an arbiter to resolve disagreements.

```yaml
model: openai/gpt-4o          # default for all agents

agents:                        # per-agent overrides
  codegen:
    model: anthropic/claude-opus-4-6
  analyzer:
    model: gemini/gemini-2.5-pro
  ideator:
    model: deepseek/deepseek-chat
  compactor:
    model: anthropic/claude-haiku-4-5-20251001
```

## 🛡️ Safety

Sigil is designed to protect trust in the repository. One bad PR kills trust forever, so it's conservative by default.

- **Isolated execution** — code changes happen in git worktrees, never the main working tree
- **Checks gate output** — PRs that fail lint or tests are retried or downgraded to issues
- **Structured editing** — agents use structured tools, not freeform shell commands
- **Deduplication** — existing PRs and issues are checked before publishing
- **Convention-aware** — detects and follows `AGENTS.md`, `.cursorrules`, `CLAUDE.md`, and similar repo instructions
- **Rate-limited** — caps on PRs, issues, and ideas per run prevent spam
- **Learns from mistakes** — previous attempts inform future runs

## 🔄 GitHub Action

Add Sigil to any repo with a single workflow file. It runs on a schedule and opens PRs automatically.

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

Sigil uses [LiteLLM](https://docs.litellm.ai/) — pass whichever API key your model provider needs via `env:`:

```yaml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}      # Anthropic
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}            # OpenAI
  OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}    # OpenRouter
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}            # Google Gemini
```

<details>
<summary>📌 Action inputs</summary>

| Input | Default | Description |
|---|---|---|
| `github-token` | `github.token` | Token for git and PR operations. Pass a [PAT](https://github.com/settings/tokens) to trigger CI on Sigil PRs |
| `dry-run` | `false` | Passed as `--dry-run` |
| `sigil-version` | `sigil @ git+https://github.com/dylan-murray/sigil.git` | Package spec for `uv tool install` |

Models are configured in `.sigil/config.yml`, not in the action.

</details>

<details>
<summary>⚙️ Required repo settings</summary>

For Sigil to create PRs and push commits, you need to enable two things in your repo settings:

1. **Settings → Actions → General → Workflow permissions** → select **"Read and write permissions"**
2. **Settings → Actions → General → Workflow permissions** → check **"Allow GitHub Actions to create and approve pull requests"**

Without these, Sigil can analyze your code but will fail when trying to open PRs.

</details>

## 🔌 MCP Support

Sigil connects to [Model Context Protocol](https://modelcontextprotocol.io/) servers and exposes their tools to all agents. Give Sigil access to Notion, Slack, Jira, databases, or any MCP-compatible service.

```yaml
mcp_servers:
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

Environment variable placeholders (`${VAR}`) are resolved at runtime — secrets stay out of config. In CI, pass them as `env:` on the Sigil step.

<details>
<summary>📌 MCP server config fields</summary>

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | Yes | string | Server identifier |
| `command` | One of | string | Stdio transport: command to run |
| `url` | One of | string | SSE transport: HTTP endpoint |
| `args` | No | list | Arguments for stdio command |
| `env` | No | dict | Env vars for stdio process (supports `${VAR}`) |
| `headers` | No | dict | HTTP headers for SSE (supports `${VAR}`) |
| `timeout` | No | float | Connection timeout in seconds (default: 60) |
| `purpose` | No | string | What this server provides — used in agent prompts |

Tools are namespaced as `mcp__<server>__<tool>` to avoid collisions.

</details>

## 🎛️ Configuration

Sigil creates `.sigil/config.yml` on first run. Everything is optional except `model`.

<details>
<summary>📌 Full config reference</summary>

```yaml
version: 1
model: anthropic/claude-sonnet-4-6

boldness: bold                  # conservative | balanced | bold | experimental
focus:                          # what to look for
  - tests
  - dead_code
  - security
  - docs
  - types
  - features
  - refactoring

ignore:                         # glob patterns to skip during discovery and execution
  - "vendor/**"
  - "*.generated.*"

max_prs_per_run: 3
max_issues_per_run: 5
max_ideas_per_run: 15
idea_ttl_days: 180              # auto-prune stale ideas
max_retries: 1
max_parallel_agents: 3
max_tool_calls: 50              # per-agent tool call limit
max_cost_usd: 20.0              # cost guardrail per run

validation_mode: single         # single | parallel (two reviewers + arbiter)
test_agent: true                # run a test-writing agent after code changes

pre_hooks: []                   # shell commands run before code generation (failure aborts)
post_hooks: []                  # shell commands run after code generation (failure retries)

fetch_github_issues: true       # pull GitHub issues for context
max_github_issues: 25
directive_phrase: "@sigil work on this"

agents:                         # per-agent model overrides
  codegen:
    model: anthropic/claude-opus-4-6
  analyzer:
    model: gemini/gemini-2.5-pro
  compactor:
    model: anthropic/claude-haiku-4-5-20251001
```

</details>

### 🎚️ Boldness Levels

| Level | Behavior |
|---|---|
| `conservative` | Obvious, low-risk fixes only |
| `balanced` | Safe refactors and common maintenance |
| `bold` | Broader cleanup, docs, and testing improvements |
| `experimental` | Speculative ideas and larger suggestions |

### 🔑 Provider Credentials

Export a key for each provider you use:

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export OPENROUTER_API_KEY=...
export GEMINI_API_KEY=...
export DEEPSEEK_API_KEY=...
```

## 📁 The `.sigil/` Directory

Sigil stores project state in `.sigil/` at the repo root. Most of it is committed so the agent keeps context across runs, machines, and CI.

| Path | Committed | Purpose |
|---|---|---|
| `config.yml` | ✅ | User-controlled configuration |
| `memory/` | ✅ | Persistent repo knowledge maintained by Sigil |
| `ideas/` | ✅ | Overflow ideas saved for later runs |
| `worktrees/` | ❌ | Temporary isolated execution sandboxes |

## 📖 CLI Reference

```text
sigil run [OPTIONS]

Options:
  --repo, -r PATH     Repository path
  --dry-run           Analyze only; no PRs or issues
  --model, -m TEXT    Override configured model
  --trace             Write LLM trace to .sigil/traces/last-run.json
  --refresh           Force a full knowledge rebuild
  --version, -v       Print version and exit
```

## 🛠️ Development

```bash
git clone https://github.com/dylan-murray/sigil.git
cd sigil
uv sync

uv run pytest tests/ -x -q
uv run ruff check .
uv run ruff format .
uv run sigil run --repo . --dry-run
```

## License

Apache 2.0
