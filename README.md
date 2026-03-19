# Sigil

Autonomous repo improvement agent — finds improvements and ships PRs while you sleep.

## Quickstart

```bash
uv tool install sigil
sigil init --repo .
sigil run --repo .
```

## Configuration

After `sigil init`, configure `.sigil/config.yml`:

```yaml
version: 1
model: anthropic/claude-sonnet-4-20250514   # or openai/gpt-4o, gemini/gemini-pro, etc.
boldness: bold                         # conservative | balanced | bold | experimental
focus:
  - tests
  - dead_code
  - security
  - docs
  - types
  - features
max_prs_per_run: 3
schedule: "0 2 * * *"
```

## Models

Sigil uses [litellm](https://github.com/BerriAI/litellm) under the hood, so any LLM provider works. Set the appropriate API key:

```bash
export ANTHROPIC_API_KEY=...   # for anthropic/* models
export OPENAI_API_KEY=...      # for openai/* models
export GEMINI_API_KEY=...      # for gemini/* models
```

## GitHub Action

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
      - run: uv tool install sigil
      - run: sigil run --repo . --ci
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## License

MIT
