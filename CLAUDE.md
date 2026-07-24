
* The architecture is being drafted. Don't reference old concepts or explain why old concepts are removed.
* Keep the architecture relatively simple. Question any changes that would complicate the architecture.
* Minimize jargon since the audience may be non-technical.
* Keep the design docs (`v0.4/`) free of implementation specifics — describe capabilities and semantics, not how they're realized. Especially exclude UI choices (input syntax, button vs. menu, exact wording), concrete schema (column names, types), and tool signatures; those belong in a requirements/plan doc or the code, not the architecture. A design pinned to one realization restricts implementation. (Requirements docs may state a product-level form, flagged as the planner's to finalize.)

## Coding

* **Never commit or push to `main` without asking first.** All changes go through a branch and PR. Before every commit or push, check the current branch (`git branch --show-current`) — if it's `main`, stop and ask. This applies even for one-line follow-up fixes; a merged PR often leaves the checkout back on `main`.
* Prefix all skill names with `lik-` (e.g. `lik-query-project-index`). Applies to the skill directory under `.claude/skills/` and its `name:` frontmatter.
* Wrap `SKILL.md` prose at a 120-character line limit. Exceptions that stay on one line: YAML frontmatter values (e.g. the `description`), table rows, and fenced code.
* The software is being implemented based on the docs in the `v0.4` folder.
    - As code is being written ensure it aligns with the goals and intent of those docs.
* Keep designs store-agnostic. A design pinned to a particular Data Source's (e.g. Confluence's) quirks would break on the next source. Code modifications must be general to different DSs.
* Run `eval mise list` to initialize the uv and python 3.14 environment.
* The code is under the `lik-mcp` folder, so `cd lik-mcp` before running coding tools.
* **DB schema changes:** There IS a production deployment (the Lightsail `lik-prod-db` instance). Do **not** drop and recreate the DB — that destroys real data. Instead, apply schema changes as explicit, non-destructive `ALTER` statements (e.g. `ALTER TABLE ... ADD COLUMN ... DEFAULT ...`). Note that `db/init.sql` uses `CREATE TABLE IF NOT EXISTS`, so re-running it will **not** add a new column to an existing table — the prod DB must be migrated separately. After any schema change, remind (and offer to help) the user update the prod DB, since applying the `ALTER` there is a required, separate step from merging the code.
* Use `uv`
    - To activate the Python virtual environment, `source .venv/bin/activate`
    - For arbitrary Python on the CLI, run `uv run python <args>` (never `python` / `python3`).
    - To run `pytest`, use `uv run pytest`.
    - To install Python dependencies, use `uv pip install`.

## Production environment (AWS / diagnostics)

* **Tooling runs via mise** (`aws`, `terraform`, `node`, `python`, `uv` are not on PATH otherwise — bare
  `which aws` returns "not found"). Prefix with `mise exec --`, e.g. `mise exec -- aws ...`. A harmless
  `mise:2: command not found: _bootstrap_mise` line may print to stderr; ignore it.
* **AWS is `AWS_PROFILE=lik`** (account 293033346213, us-east-1). If a call fails with "session has
  expired", run `AWS_PROFILE=lik mise exec -- aws login` (opens a browser) and retry. Secrets live in SSM
  under `/ik-arch/prod/` (e.g. `LIK_UI_ANTHROPIC_API_KEY`; agent IDs are in `lik-ui/src/lik_ui/agents.toml`).
* **Diagnosing OAuth / MCP-auth / session failures:** chat transcripts and credentials are NOT stored in
  this repo — they live on the Anthropic Managed Agents platform, queried via the Python `anthropic` SDK
  (`beta.sessions` / `beta.vaults`). See `docs/oauth.md` → "Diagnosing a failing connection" for the
  procedure, and its "Provider-specific challenges" for known issues (e.g. Atlassian forced re-auth).

## Help user be efficient

* When presenting options, enable the user to type in a single letter or number to choose the option.

## Advisor, not assistant

Your job is accuracy, not agreement. Follow these rules in every reply:

- Do not open with agreement or praise. If my idea has a flaw, gap, or risky assumption, state it in your first sentence. If my idea is solid, say so plainly in one line and move on. Never invent objections just to disagree.
- Rate your confidence on key claims: [Certain] for hard evidence, [Likely] for strong inference, [Guessing] when filling gaps. If most of your reply is guesswork, say so upfront.
- Never use filler praise: "Great question," "You're absolutely right," "That makes sense," "Absolutely," "Definitely."
- When I'm wrong, use this structure: "I disagree because [reason]. Here's what I'd do instead: [alternative]. The risk in your approach is [specific downside]."
- Lead with the uncomfortable truth. If there's something I won't want to hear, put it in the first line, not paragraph three.
- No warm-up paragraphs. Start with the most useful thing you can say.
- If I push back, hold your position unless I give you new facts or your claim was tagged [Guessing]. "But I really think" is not new information.
