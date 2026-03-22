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
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License"></a>
</p>

---

Sigil is an LLM-agnostic autonomous agent that watches your repo, finds improvements, and **ships pull requests while you sleep**. Bring any model — OpenAI, Anthropic, Gemini, or any of 100+ providers supported by [litellm](https://github.com/BerriAI/litellm). Sigil runs on a schedule, analyzes your entire codebase, and opens small, safe PRs for things it can fix. Ideas it doesn't have bandwidth to tackle in the current run get filed as issues for later.

Every dev tool today waits for you to ask. Sigil doesn't. It fits into the way you already work — your models, your CI, your repo. Point it at a codebase and walk away.

## ⚡ Quickstart

```bash
# install
uv tool install sigil

# run — auto-creates config on first run
sigil run --repo .

# just look, don't touch
sigil run --repo . --dry-run
```

**You need:** Python 3.11+ &bull; [uv](https://docs.astral.sh/uv/) &bull; an LLM API key &bull; `GITHUB_TOKEN` for PRs/issues

## 📁 The `.sigil/` Directory

Sigil stores everything it needs in `.sigil/` at your repo root. This directory is **committed to git** (except for temporary worktrees), so Sigil's knowledge carries across CI runs, machines, and contributors.

```
.sigil/
├── config.yml          # 🎛️  Your configuration — models, boldness, focus, MCP servers
├── memory/             # 🧠  Persistent knowledge base (auto-managed)
│   ├── INDEX.md        #     Quick-reference index of all knowledge files
│   ├── project.md      #     Tech stack, build/test/lint commands
│   ├── architecture.md #     Modules, components, data flow
│   ├── patterns.md     #     Coding conventions, error handling, import style
│   ├── dependencies.md #     External deps, internal module graph
│   ├── testing.md      #     Test framework, patterns, coverage gaps
│   └── working.md      #     Rolling log: what worked, what failed, what's next
├── ideas/              # 💡  Saved improvement ideas for future runs
└── worktrees/          # 🚧  Temporary execution sandboxes (gitignored)
```

| Path | Committed? | Managed by |
|---|---|---|
| `config.yml` | ✅ Yes | **You** — edit to tune Sigil's behavior |
| `memory/` | ✅ Yes | **Sigil** — auto-built on first run, updated each run after |
| `ideas/` | ✅ Yes | **Sigil** — overflow ideas saved for future runs |
| `worktrees/` | ❌ No | **Sigil** — temporary git worktrees, gitignored |

Memory is built by reading your entire codebase on the first run, then **compacted** incrementally when `git HEAD` changes. `working.md` is a fixed-size rolling summary updated at the end of every run — not a growing log. Because it's committed, Sigil picks up where it left off in CI with no external database or cache.

## 🎛️ Configuration

First run auto-creates `.sigil/config.yml`. Tweak it:

```yaml
version: 1
model: anthropic/claude-sonnet-4-6           # any litellm-supported model
boldness: balanced                            # conservative | balanced | bold | experimental
focus:                                        # what to look for
  - tests                                     # missing tests, coverage gaps
  - dead_code                                 # unused functions, imports, variables
  - security                                  # vulnerabilities, unsafe patterns
  - docs                                      # outdated or missing documentation
  - types                                     # missing type annotations
ignore:                                       # glob patterns to skip
  - "vendor/**"
  - "*.generated.*"
max_prs_per_run: 3                            # won't spam you with PRs
max_issues_per_run: 5                         # or issues
max_ideas_per_run: 10                         # cap on ideas per run
max_retries: 2                                # retry failed executions
max_parallel_agents: 3                        # concurrent worktrees
validation_mode: single                       # single | parallel (two reviewers + arbiter)
lint_cmd: null                                # optional, auto-detected
test_cmd: null                                # optional, auto-detected
fetch_github_issues: true                     # check existing issues to avoid dupes
max_github_issues: 50                         # how many issues to fetch
directive_phrase: "@sigil work on this"       # magic phrase in issues to trigger work
agents:                                       # per-agent model overrides (optional)
  codegen:
    model: anthropic/claude-opus-4-6    # strongest model for code generation
  compactor:
    model: anthropic/claude-haiku-4-5-20251001  # cheap model for knowledge compaction
```

Agent names: `analyzer`, `ideator`, `validator`, `codegen`, `discovery`, `compactor`, `memory`, `reviewer`, `arbiter`. Any agent without a model override uses the top-level `model`. The `reviewer` and `arbiter` agents are only used when `validation_mode: parallel` is set.

### 🎚️ Boldness — pick your comfort zone

| | Level | What it does |
|---|---|---|
| 🐢 | `conservative` | Only the obvious stuff — typos, unused imports, dead code |
| ⚖️ | `balanced` | Safe refactors, missing tests, simple improvements |
| 🔥 | `bold` | New tests, doc rewrites, pattern fixes |
| 🚀 | `experimental` | Feature ideas, architectural suggestions, creative leaps |

### 🤖 Model — bring your own

Powered by [litellm](https://github.com/BerriAI/litellm). Set `model` in config to any of 100+ supported providers:

```bash
export ANTHROPIC_API_KEY=...   # anthropic/claude-sonnet-4-6
export OPENAI_API_KEY=...      # openai/gpt-4o
export GEMINI_API_KEY=...      # gemini/gemini-2.5-pro
```

Override at runtime with `sigil run --model openai/gpt-4o`.

## 🔄 GitHub Action — set it and forget it

Sigil ships a reusable composite action. Drop this in `.github/workflows/sigil.yml`:

```yaml
name: Sigil
on:
  schedule:
    - cron: '0 2 * * *'
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
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

The action handles uv, Node (for MCP stdio servers), and Sigil installation automatically. All config comes from `.sigil/config.yml`.

| Input | Default | Description |
|---|---|---|
| `anthropic-api-key` | — | Sets `ANTHROPIC_API_KEY` |
| `openai-api-key` | — | Sets `OPENAI_API_KEY` |
| `model` | — | Override model from config |
| `dry-run` | `false` | Analyze only, no PRs/issues |
| `sigil-version` | Latest from `main` | Custom package spec |

## 🔌 MCP Support — extend with external tools

Sigil can connect to [MCP](https://modelcontextprotocol.io/) servers, giving agents access to external tools like filesystems, databases, or custom APIs. Configure servers in `.sigil/config.yml` and they're available to all agents automatically.

Supports both **stdio** (local processes) and **SSE** (remote HTTP) transports. Tools are namespaced as `mcp__<server>__<tool>` (matching the convention used by Claude Code, Agent SDK, and Codex), and each server gets its own connection lock and timeout handling.

The optional `purpose` field gives agents category-level context — instead of a flat tool listing, prompts read "You have access to **notion** tools for product requirements and design docs". It's worth setting:

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

### 🔑 MCP credentials with `${VAR}` interpolation

MCP configs support `${VAR}` placeholders in `env` and `headers` fields. At runtime, Sigil replaces these with the matching environment variable — keeping secrets out of your committed config.

**Locally**, export the variable before running:

```bash
export NOTION_API_KEY=secret-...
sigil run
```

**In CI**, pass them as `env:` on the action step:

```yaml
- uses: dylan-murray/sigil@main
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
  env:
    SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
    NOTION_API_KEY: ${{ secrets.NOTION_API_KEY }}
```

No extra action inputs needed — environment variables on the step are automatically available to `sigil run`. Store secrets in **GitHub repo settings → Secrets → Actions** and reference them with `${{ secrets.NAME }}`. If a `${VAR}` is referenced in config but missing from the environment, Sigil raises a clear error with the variable name.

## 🔬 How It Works

```
Discover → Learn → Connect MCP → Analyze + Ideate → Validate → Execute → Publish → Remember
```

| Stage | What happens |
|---|---|
| **Discover** | Scans repo structure, git history, languages |
| **Learn** | Builds persistent knowledge about your codebase |
| **Connect MCP** | Connects to configured MCP servers, discovers available tools |
| **Analyze + Ideate** | Two LLM agents find issues and generate ideas in parallel |
| **Validate** | Senior-engineer agent approves, adjusts, or vetoes each finding; checks against existing GitHub issues. Optional `parallel` mode runs two independent reviewers + an arbiter to resolve disagreements |
| **Execute** | Parallel agents implement fixes in isolated git worktrees |
| **Publish** | Opens PRs for safe fixes, files issues for risky ones |
| **Remember** | Updates working memory so it never repeats itself |

## 🛡️ Safety — Sigil won't break your stuff

| Guarantee | How |
|---|---|
| **Tests must pass** | PRs that fail lint/tests get retried, then downgraded to issues |
| **Isolated execution** | All changes happen in git worktrees — your working tree is untouched |
| **No shell access** | Execution agents use structured tools only (read/edit/create) |
| **Deduplication** | Fetches existing GitHub issues and PRs — won't open duplicates |
| **Respects your conventions** | Detects AGENTS.md, .cursorrules, copilot-instructions and follows them |
| **Rate-limited** | Configurable caps on PRs, issues, and ideas per run |
| **Has a memory** | Remembers what it tried before — won't repeat rejected changes |

## 🧠 Knowledge System

Sigil builds a persistent brain about your project in `.sigil/memory/`. Every agent reads these files before making any changes — Sigil understands your codebase before it touches it.

| File | What it knows |
|---|---|
| `project.md` | What this project is, tech stack, how to build/test/lint |
| `architecture.md` | Modules, components, data flow |
| `patterns.md` | Your coding conventions, error handling, import style |
| `dependencies.md` | External deps, internal module graph |
| `testing.md` | Test framework, patterns, coverage gaps |
| `working.md` | What it's done, what worked, what to try next |

## 📖 CLI Reference

```
sigil run [OPTIONS]

Options:
  --repo PATH       Repository path (default: .)
  --dry-run         Analyze only — don't open PRs or issues
  --model MODEL     Override the model from config
  --version, -v     Print version and exit
```

## 🛠️ Development

```bash
git clone https://github.com/dylan-murray/sigil.git
cd sigil
uv sync

uv run pytest tests/ -x -q        # test
uv run ruff check .                # lint
uv run ruff format .               # format
uv run sigil run --repo . --dry-run  # test drive
```

## License

MIT