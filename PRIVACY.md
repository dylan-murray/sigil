# Privacy Policy

**Last updated:** March 30, 2026

Sigil is an open source tool that runs in your own environment. This policy
explains what data Sigil accesses and where it goes.

## What Sigil Accesses

When you run Sigil (locally or via GitHub Actions), it reads:

- **Source code** from the repository it's pointed at
- **Git history** (recent commits, file listings, branch info)
- **GitHub issues and PRs** (via `GITHUB_TOKEN`) for deduplication
- **Configuration** from `.sigil/config.yml`

## Where Data Is Sent

Sigil sends repository content to the **LLM provider you configure** (e.g.
Anthropic, OpenAI, Google, OpenRouter, DeepSeek). This is required for Sigil
to analyze your code and generate improvements.

- **You choose the provider.** Sigil uses [LiteLLM](https://docs.litellm.ai/)
  and sends data only to the provider specified in your `model` configuration.
- **You provide the API key.** Sigil never stores, logs, or transmits your
  API keys. They are read from environment variables at runtime.
- **Each provider has its own privacy policy.** Review your provider's data
  handling practices before use.

Sigil also interacts with the **GitHub API** (via `GITHUB_TOKEN`) to:

- Open pull requests and issues
- Push branches
- Fetch existing issues for deduplication

## What Sigil Does NOT Do

- Does not collect analytics or telemetry
- Does not phone home to any Sigil-operated server
- Does not store or transmit your API keys
- Does not send data to any party other than your configured LLM provider
  and GitHub
- Does not sell, share, or monetize your data in any way

## Data Storage

Sigil stores operational data locally in the `.sigil/` directory of your
repository:

| Path | Contains | Sensitive? |
|---|---|---|
| `config.yml` | Your configuration | No (no secrets) |
| `memory/` | Compressed knowledge about the repo | No |
| `ideas/` | Feature ideas for future runs | No |
| `traces/` | LLM call metadata (when `--trace` is used) | No (no prompts or responses stored by default) |

These files are local to your repository. The `memory/` and `ideas/`
directories are committed to git by default so Sigil retains context across
runs. You can gitignore them if you prefer.

## Third-Party Services

Sigil integrates with these services only when you explicitly configure them:

- **LLM providers** — via API key you provide
- **GitHub** — via `GITHUB_TOKEN`
- **MCP servers** — any Model Context Protocol servers you configure in
  `.sigil/config.yml`

Each integration is opt-in and controlled by your configuration.

## Contact

For privacy questions, open an issue at
https://github.com/dylan-murray/sigil/issues or email dylnmurry@gmail.com.
