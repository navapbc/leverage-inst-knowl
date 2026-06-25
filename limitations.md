# Known Limitations

## Confluence MCP: Page Version Number Not Available

The Confluence MCP connector (`01fd8586-e417-4e54-ae66-45006d1e08b1`) does not expose a page **version number**. Neither `getConfluencePage` nor `searchConfluenceUsingCql` (with `expand=version`) returns a version field in the response body.

**What this rules out:** staleness checks that compare a stored version *number* against the live page's version number. That specific mechanism cannot work.

**What it does NOT rule out:** detecting whether a page's content has *changed* since DL last saw it. A version number is one way to detect change — it is not the only one.

**No stable native change signal either (verified live).** Beyond the missing version number, the connector exposes **no** stable timestamp to use as a marker. Both `getConfluencePage` and `searchConfluenceUsingCql` return `lastModified` only as a *human-readable relative string* (e.g. `"about 5 hours ago"`, `"Jun 18, 2026"`), and `expand=version` / `expand=history.lastUpdated` are silently ignored. A relative string changes on every read even when the page hasn't, so it is unusable as an equality marker (it would flag every page as edited). The raw Confluence REST API does return `version.when` / `version.createdAt`, but this MCP connector does not pass them through.

**Consequence:** for Confluence via this connector, a **content hash of the page body is the only viable content-state marker** — there is no usable native signal. DL fetches the body via `getConfluencePage` (markdown), so it hashes that body and compares hashes; change detection = `stored hash ≠ current hash`, needing zero extra MCP capability.

**Design impact:** confirmations and `catalog.source_refs[]` anchor to an opaque content-state marker compared by equality, not to a version number. See [docs/brainstorms/2026-06-25-02-confirmation-content-state-marker-requirements.md](docs/brainstorms/2026-06-25-02-confirmation-content-state-marker-requirements.md). For Confluence the marker is a content hash of the page body — not `lastModified` — so change detection is not blocked by the missing version number.
