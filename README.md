<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/logo.svg">
    <img alt="Sigil" src="assets/logo.svg" width="500">
  </picture>
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

Sigil is an autonomous AI agent that watches your repo, finds improvements, and **ships pull requests while you sleep**. It runs on a schedule, analyzes your entire codebase, and opens small, safe PRs for things it can fix — and files issues for things that need a human.

Every dev tool today waits for you to ask. Sigil doesn't. Point it at a repo and walk away.

> **One command. Zero babysitting. Wake up to better code.**

## 🎬 What happens when you run `sigil run`

```
  ┌─────────────┐
  │  sigil run   │
  └──────┬──────┘
         │
    ┌────▼────┐     scans files, git history, languages
    │ Discover │
    └────┬────┘
         │
   ┌─────▼─────┐    builds knowledge: architecture, patterns, deps
   │  Learn     │
   └─────┬─────┘
         │
  ┌──────▼──────┐   two LLM agents work in parallel
  │ Analyze  +  │   one finds bugs, dead code, security issues
  │ Ideate      │   one generates feature ideas
  └──────┬──────┘
         │
  ┌──────▼──────┐   senior-engineer agent approves, adjusts, or vetoes
  │  Validate   │
  └──────┬──────┘
         │
  ┌──────▼──────┐   parallel agents implement fixes in isolated worktrees
  │  Execute    │   runs your lint + tests to verify each change
  └──────┬──────┘
         │
  ┌──────▼──────┐   opens PRs for safe fixes
  │  Publish    │   files issues for risky ones
  └──────┬──────┘   deduplicates against what's already open
         │
  ┌──────▼──────┐
  │  Remember   │   updates memory so it never repeats itself
  └─────────────┘
```

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

## 🎛️ Configuration

First run creates `.sigil/config.yml`. Tweak it:

```yaml
version: 1
model: anthropic/claude-sonnet-4-6    # any litellm-supported model
boldness: bold                         # how adventurous should Sigil be?
focus:                                 # what to look for
  - tests                              # missing tests, coverage gaps
  - dead_code                          # unused functions, imports, variables
  - security                           # vulnerabilities, unsafe patterns
  - docs                               # outdated or missing documentation
  - types                              # missing type annotations
  - features                           # small feature ideas and enhancements
ignore: []                             # glob patterns to skip (e.g., ["vendor/**"])
max_prs_per_run: 3                     # won't spam you with PRs
max_issues_per_run: 5                  # or issues
lint_cmd: ""                           # your lint command
test_cmd: ""                           # your test command
max_parallel_agents: 3                 # concurrent worktrees
```

### Boldness — pick your comfort zone

| | Level | What it does |
|---|---|---|
| 🐢 | `conservative` | Only the obvious stuff — typos, unused imports, dead code |
| ⚖️ | `balanced` | Safe refactors, missing tests, simple improvements |
| 🔥 | `bold` | New tests, doc rewrites, pattern fixes |
| 🚀 | `experimental` | Feature ideas, architectural suggestions, creative leaps |

## 🤖 LLM Support — bring your own model

Powered by [litellm](https://github.com/BerriAI/litellm). **100+ models** from any provider:

```bash
export ANTHROPIC_API_KEY=...   # anthropic/claude-sonnet-4-6
export OPENAI_API_KEY=...      # openai/gpt-4o
export GEMINI_API_KEY=...      # gemini/gemini-2.5-pro
```

Override per-run:

```bash
sigil run --model openai/gpt-4o
```

## 🔄 GitHub Action — set it and forget it

Drop this in `.github/workflows/sigil.yml` and Sigil runs every night at 2am:

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

      - uses: astral-sh/setup-uv@v4

      - name: Install Sigil
        run: uv tool install sigil

      - name: Run Sigil
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: sigil run
```

## 🛡️ Safety — Sigil won't break your stuff

| Guarantee | How |
|---|---|
| **Tests must pass** | PRs that fail lint/tests get retried, then downgraded to issues |
| **Isolated execution** | All changes happen in git worktrees — your working tree is untouched |
| **No shell access** | Execution agents use structured tools only (read/edit/create) |
| **Deduplication** | Won't open a PR or issue if one already exists for the same thing |
| **Rate-limited** | Configurable caps on PRs, issues, and ideas per run |
| **Has a memory** | Remembers what it tried before — won't repeat rejected changes |

## 🧠 Knowledge System

Sigil builds a persistent brain about your project in `.sigil/memory/`:

| File | What it knows |
|---|---|
| `project.md` | What this project is, tech stack, how to build/test/lint |
| `architecture.md` | Modules, components, data flow |
| `patterns.md` | Your coding conventions, error handling, import style |
| `dependencies.md` | External deps, internal module graph |
| `testing.md` | Test framework, patterns, coverage gaps |
| `working.md` | What it's done, what worked, what to try next |

Knowledge auto-rebuilds when git HEAD changes. Sigil reads your code before it touches your code.

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
git clone https://github.com/yourusername/sigil.git
cd sigil
uv sync

uv run pytest tests/ -x -q        # test
uv run ruff check .                # lint
uv run ruff format .               # format
uv run sigil run --repo . --dry-run  # test drive
```

## License

MIT