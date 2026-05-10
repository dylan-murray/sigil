<!-- head: fc6cf7b299cd8617beb661fd7f57ee3c810447bf | manifest: 1c483ed0ae47038d2cf9c124020be942c44f2f5ec023b22510712e4bc9481391 | updated: 2026-05-10T18:29:08Z -->

# Knowledge Index

## agent-framework.md
Agent Framework — Unified Tool and Agent Abstractions: Core Classes, Status Callbacks

## api.md
API Reference — Core Data Structures, Public Functions, and Tool Schemas: Core Data Structures, Public Functions by Module, Constants, Removed

## architecture.md
Pipeline Architecture — 7-Stage Async Agentic Workflow: Pipeline Stages, Execution Isolation, Agent Loop

## configuration.md
Config File Format — .sigil/config.yml with Agent and Model Settings: Key Settings, Per-Agent Configuration, Model Overrides, Run Budget, Post Hooks, MCP Servers, AgentSpec Dataclass, Default Max Iterations, ... (+1 more)

## dependencies.md
Dependencies: Package Manager, Runtime Dependencies, Development Dependencies, Internal Module Dependency Graph, External Service Dependencies, Model Configuration, Removed Dependencies

## execution-model.md
Execution Model — Worktree Isolation, Inline PR Publishing, Parallel Execution, Directive Bypass, and Cleanup: Overview, Worktree Architecture, Code Generation Loop (Agent Framework), Cost Optimization in Executor, Failure Downgrade, Parallel Execution, Directive Item Bypass, Inline PR Publishing, ... (+5 more)

## executor-tools.md
Worktree-Based Parallel Execution with Pre/Post Hook Pipeline: Tools, Safety Mechanisms, Summary Generation from Diff, Removed Features

## github-integration.md
GitHub Integration — Authentication, Dedup, PR/Issue Publishing, Directive Issues, and Inline Execution: Authentication & Setup, Deduplication System, Directive Issues, Pull Request Flow, Issue Flow, Label Management, Model Attribution in PR Bodies, Rate Limiting & Error Handling, ... (+3 more)

## knowledge-management.md
Knowledge Indexing and Working Memory Persistence: Persistent Knowledge, Working Memory (`working.md`), Staleness Check

## knowledge-system.md
Knowledge System: Overview, Directory Structure, Staleness Detection, Compaction Flow (Two Modes), Key Constants (knowledge.py), Knowledge Selection, LLM Tools in knowledge.py, Per-Agent Model for Compaction, ... (+7 more)

## patterns.md
Coding Patterns: Python Standards, Naming Conventions, Dataclass Pattern, Tool Class Pattern, Agent Class Pattern, Config Access Pattern, Async Subprocess Pattern, Validation Spec Pattern, ... (+1 more)

## project.md
Sigil — Autonomous Repo Improvement Agent (Python 3.11/litellm/uv): Tech Stack, Build and Test: Tech Stack, Build and Test, Version

## testing-patterns.md
pytest + pytest-asyncio Test Setup with Mock Patterns: Unit Tests (`tests/unit/`), Integration Tests (`tests/integration/`)

## testing.md
Testing — pytest + pytest-asyncio with Mock Patterns and Coverage: Framework & Configuration, Directory Structure, CI Pipelines, Test Conventions, Mocking Patterns, Coverage by Module, Running Tests
