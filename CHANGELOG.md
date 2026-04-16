# Changelog

All notable changes to this plugin are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

Automated updates are managed by
[release-please](https://github.com/googleapis/release-please) based on
[Conventional Commit](https://www.conventionalcommits.org/) messages.

## [0.1.0] - 2026-04-17

### Added

- Claude Code plugin layout (`.claude-plugin/plugin.json`, self-hosted marketplace at `.claude-plugin/marketplace.json` named `claude-harness`).
- Workflow skill at `skills/harness/SKILL.md` implementing a 5-phase pipeline: Clarify → Context → Plan → Generate → Evaluate.
- Deterministic CLI at `scripts/harness.py` (stdlib + PyYAML) with 13 subcommands: `slug`, `scan`, `next`, `log`, `verify`, `conflicts`, `summary`, `approve`, `archive-plan`, `classify-failure`, `stale`, `cleanup`, `list`, `config`.
- JSON Schemas for all persisted state: task sidecar, plan YAML, approval, per-slug config.
- 79 unit tests covering every subcommand plus resume-point, stale detection, and classify-failure matrix logic.
- Three committed dogfood runs under `dogfood/` documenting real pipeline behavior and the frictions they surfaced.
