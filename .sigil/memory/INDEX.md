<!-- head: 856d4972755ad93e941365f3e2274b7b83f8bb4d | manifest: 562746f47015c3e4df75e2daadc8749037967f9d75dc8db72300b10f09afac70 | updated: 2026-04-01T00:24:26Z -->

# Knowledge Index

## agent-framework.md
Agent Framework — Unified Tool and Agent Abstractions: Core Classes, Agent Features

## api.md
API Reference — Core Data Structures, Public Functions, and Tool Schemas: Core Data Structures, Public Functions by Module, LLM Tool Schemas, Constants, Known Notes

## architecture.md
Pipeline Architecture — 8-Stage Async Agentic Workflow: Pipeline Stages, Execution Isolation

## configuration.md
Config File Format — .sigil/config.yml with Agent and Model Settings: Key Settings, Run Budget

## dependencies.md
Dependencies: Package Manager, Runtime Dependencies, Development Dependencies, Internal Module Dependency Graph, External Service Dependencies, Model Configuration, Removed Dependencies

## execution-model.md
Execution Model: Overview, Worktree Architecture, Code Generation Loop (Agent Framework), Cost Optimization in Executor, Failure Downgrade, Parallel Execution, Memory Conflict Resolution During Rebase, ExecutionResult Interpretation, ... (+4 more)

## executor-tools.md
Worktree-Based Parallel Execution with Pre/Post Hook Pipeline: Tools, Safety Mechanisms

## github-integration.md
GitHub Integration: Authentication & Setup, Deduplication System, Pull Request Flow, Issue Flow, Label Management, Rate Limiting & Error Handling, Publishing Limits, Branch Cleanup, GitHub Actions Integration, Async Wrapping Pattern: Authentication & Setup, Deduplication System, Pull Request Flow, Issue Flow, Label Management, Rate Limiting & Error Handling, Publishing Limits, Branch Cleanup, ... (+2 more)

## knowledge-management.md
Knowledge Indexing and Working Memory Persistence: Persistent Knowledge, Working Memory (`working.md`), Staleness Check

## knowledge-system.md
Knowledge System: Overview, Directory Structure, Staleness Detection, Compaction Flow (Two Modes), Key Constants (knowledge.py), Knowledge Selection, LLM Tools in knowledge.py, Per-Agent Model for Compaction, ... (+7 more)

## patterns.md
Coding Patterns: Python Standards, Naming Conventions, Dataclass Pattern, Tool Class Pattern (Agent Framework), Agent Class Pattern (Agent Framework), Tool-Use Pattern (Legacy — Replaced by Agent Framework), Validation Spec Pattern, Async Subprocess Pattern, ... (+12 more)

## project.md
Sigil — Autonomous Repo Improvement Agent (Python 3.11/litellm/uv): Tech Stack, Build and Test

## testing-patterns.md
pytest + pytest-asyncio Test Setup with Mock Patterns: Unit Tests (`tests/unit/`), Integration Tests (`tests/integration/`)

## testing.md
Testing: Framework & Configuration, Directory Structure, CI Pipelines, Test Conventions, Mocking Patterns, Integration Tests, Coverage by Module, Running Tests
