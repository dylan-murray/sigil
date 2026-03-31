# Knowledge Indexing and Working Memory Persistence

Sigil maintains two types of state in `.sigil/memory/` to ensure it gets smarter over time.

## Persistent Knowledge
Managed by `knowledge.py`, this consists of markdown files describing the project architecture, patterns, and dependencies. 
- **Incremental Updates:** Sigil uses `git diff` to identify which knowledge files need updating based on recent commits.
- **Selection:** Before a task, a `selector` agent reads `INDEX.md` and loads only the relevant knowledge files into the engineer's context.

## Working Memory (`working.md`)
Managed by `memory.py`, this is a living document that tracks:
- PRs opened and issues filed.
- Implementation attempts that failed (to avoid repeating mistakes).
- Patterns and insights learned about the specific codebase.
- User feedback and rejected proposals.

## Staleness Check
Sigil stores the git HEAD SHA in `INDEX.md`. If the current HEAD matches, Sigil skips the discovery and compaction stages to save time and tokens.
