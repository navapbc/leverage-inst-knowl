---
date: 2026-07-22
topic: skill-instruction-hosting
---

# Skill Instruction Hosting & Deployment

## Summary

Skill instructions (the detailed prose that tells an AI agent how to do DL-creation and query work) live
in **GitHub** as the single source of truth, edited and reviewed through pull requests. Each skill is a
directory — a routing `SKILL.md` plus modular reference files loaded on demand — and a **GitHub Action**
deploys it to Claude Managed Agents by creating a new skill *version* via the Anthropic SDK on merge to the
main branch. Agents pin skills to `latest`, so a merged change goes live on the next run with no manual step.
The PR-plus-CI pipeline is the review gate. lik-ui, when it shows a skill's full instructions, renders them
from GitHub (the source of truth), not by downloading from Managed Agents.

---

## Problem Frame

Skill instructions currently reside only in Claude Managed Agents, so changing one means working through the
Claude Platform — awkward, and it leaves two copies (the `SKILL.md` files already in the repo, and the
uploaded skill versions) drifting apart with no single authority. The team wants one editable, versioned home
for these instructions and a clean path from "edited" to "live in a running agent," without adding app
complexity and without exposing instructions publicly.

Two premises were tested and discharged during the brainstorm:

- **"External sources need OAuth or public access."** This assumed the runtime fetches instructions live from
  an external location. It does not need to: skill instructions ship *inside* the uploaded skill version, and
  the agent loads reference files from the skill bundle on demand. No public mirror, no runtime OAuth.
- **"Editing friction justifies moving instructions out of the platform / into a live-fetched store."** Skills
  change rarely, so edit friction is paid rarely. The justification for structuring instructions as modular,
  on-demand files is **complexity and size** (the routing file loads specific detail per question), not edit
  frequency — and that modularity is a native skill feature, not a reason to fetch externally.

---

## Actors

- A1. Skill author (engineer or designated prompt author): edits skill instructions via pull request.
- A2. Reviewer: approves the PR — the human half of the deploy gate.
- A3. GitHub Action (CI): on merge, packages the skill directory and creates a new skill version on the
  Managed Agents platform via the Anthropic SDK.
- A4. Claude Managed Agents platform: stores skill versions; agents pinned to `latest` pick up new versions.
- A5. lik-ui (read-only viewer): displays a skill's full instructions to users, sourced from GitHub.

---

## Key Flows

- F1. Edit a skill
  - **Trigger:** An author needs to change skill behavior.
  - **Actors:** A1, A2
  - **Steps:** Author edits the skill directory (`SKILL.md` + reference files) in a branch → opens a PR →
    reviewer approves. Git history is the version history; revert = re-run the pipeline on an earlier commit.
  - **Outcome:** A reviewed change is merged to the main branch.
  - **Covered by:** R1, R2, R6

- F2. Deploy to Managed Agents
  - **Trigger:** A change merges to the main branch.
  - **Actors:** A3, A4
  - **Steps:** The Action packages the skill directory and calls the SDK to create a new skill version →
    agents pinned to `latest` use the new version on their next run.
  - **Outcome:** The live agents run the updated instructions; no one touches the Claude Platform by hand.
  - **Covered by:** R3, R4, R5

- F3. View a skill's full instructions in lik-ui
  - **Trigger:** A user opens a skill's detail view in lik-ui.
  - **Actors:** A5
  - **Steps:** lik-ui fetches the skill's `SKILL.md` (and, if shown, reference files) from GitHub and renders
    them.
  - **Outcome:** The user sees the authoritative instructions without lik-ui needing skill-download
    permission on the platform.
  - **Covered by:** R7

---

## Requirements

- R1. **Single source of truth in GitHub.** Skill instructions are authored and versioned in the repository.
  Managed Agents is a deploy target, not a second origin.
- R2. **Modular, on-demand instructions.** A skill is a routing `SKILL.md` plus reference files the agent
  loads only when a question calls for them, so the base instruction stays small and detail is compartmentalized
  for editing and human review.
- R3. **Automated deploy via a new version.** A GitHub Action creates a new skill *version* on merge (versions
  are immutable; deploying = adding a version, never mutating one).
- R4. **Deploy uses a standard org API key.** The credential is a standard organization API key
  (`sk-ant-api03-…`), stored as a CI secret and scoped to the workspace holding the agents/skills. No admin
  key is required.
- R5. **Agents pin to `latest`.** A merged change rolls out on the next agent run with no per-agent update
  step. Specific-version pinning remains available if staged rollout is ever wanted.
- R6. **PR + CI is the gate.** Because a skill defines agent behavior, a bad edit can silently break a running
  agent; review and CI stand in for the safety that code review provides. There is no ungated edit path.
- R7. **lik-ui reads instructions from GitHub.** The "show full instructions" view renders the authoritative
  files from the repository, not a download from Managed Agents.

---

## Implementation Notes (for planning)

*These are realization details, not architecture — captured because they were verified against the live API
and will otherwise be rediscovered painfully.*

- **SDK calls:** `skills.versions.create(skill_id, files=[…])` deploys; `agents.update(agent_id, version=…,
  skills=[{type:"custom", skill_id, version:"latest"}])` pins (verified working with a standard org key).
- **Upload gotcha 1 — single top-level folder.** Files must be nested under one top-level folder; a bare
  `SKILL.md` at the archive root returns `400: "SKILL.md file must be exactly in the top-level folder."`
- **Upload gotcha 2 — folder name matches skill name.** The top-level folder name must equal the `name:` in
  `SKILL.md` (lowercased); a mismatch returns 400.
- **Skill type for agents:** custom skills use `type: "custom"` (`type: "anthropic"` is for built-ins like
  `xlsx`/`pdf`); `version` accepts a concrete value or `"latest"`.
- **Deletion order:** a skill can't be deleted while it has versions — delete versions first (irrelevant to
  normal deploys, which only add versions).

---

## Out of Scope / Not Pursued

- **Public read-only mirror of instructions** — solves a runtime-fetch problem that doesn't exist (instructions
  ship inside the skill version).
- **External live fetch of detailed instructions at runtime** — unnecessary; on-demand loading is native to the
  skill bundle.
- **Editing skills inside lik-ui (write-through to Managed Agents)** — most app complexity, couples editing to
  the runtime with no review gate; rejected.
- **Non-engineer editing tooling** — deliberately deferred. No specific recurring non-engineer editor has been
  identified; build it only when that need is real. If it arrives, the likely shape is authoring in a Data
  Source (Confluence/Drive) with a propagation step, reusing the DL "authoritative-in-DS + propagate" pattern.
- **Resolving the skill-download credential type** — closed as won't-fix. A standard org key 403s on
  `versions.download`; the download-enabling credential type was not identified. Moot under R7 (lik-ui reads
  from GitHub).

---

## Open Assumptions

- The CI credential is a standard org API key minted the same way as the tested key; if a future key is scoped
  differently, re-verify it can create skill versions.
- Skills genuinely change infrequently. If edit frequency rises materially, revisit whether non-engineer
  editing (deferred above) is now worth building.
