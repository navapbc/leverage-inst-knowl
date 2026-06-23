Availability of MCP servers for data sources used at Nava

Each data source below is tagged with one status:

* ✅ **Official** — the vendor provides its own MCP server.
* 🔌 **Third-party** — no vendor server; access is through an integration platform (e.g. CData, Workato).
* 👥 **Community** — an unofficial, community-built server exists.
* ⛔ **None** — no MCP server is available.

### Main data sources
* **Confluence / Jira** — ✅ **Official.** Atlassian Rovo MCP Server, a cloud-hosted remote server, now generally available ([docs](https://www.atlassian.com/platform/remote-mcp-server)).
* **GitHub** — ✅ **Official.** GitHub-hosted remote MCP server, with a local Docker option ([repo](https://github.com/github/github-mcp-server)).
* **Slack** — ✅ **Official.** Slack MCP server, generally available since February 2026 ([docs](https://docs.slack.dev/ai/slack-mcp-server/)).

### Google data sources
* **Google Drive** — ✅ **Official.** Google-hosted remote MCP server.
* **Google Sheets** — 👥 **Community.** Not covered by Google's hosted endpoints (see note below). Available through community servers (e.g. [taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp)).
* **Google Docs** — 👥 **Community.** Not covered by Google's hosted endpoints (see note below). Available through the same community servers as Sheets.
* **Google Slides** — 👥 **Community.** Not covered by Google's hosted endpoints (see note below). Available through the same community servers as Sheets.

Note: Google's hosted Workspace MCP endpoints currently cover Gmail, Drive, Calendar, Chat, and Contacts — not Sheets or Docs ([docs](https://developers.google.com/workspace/guides/configure-mcp-servers)).

### SSA data sources
SSA will build a data pipeline that loads data from these sources into the BigQuery warehouse, for building BI dashboards.

* **Salesforce** — ✅ **Official.** Salesforce Hosted MCP Servers are generally available (since April 2026) and include a Data 360 query server ([docs](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/servers-reference.html)). A broader, open-source Data 360 server is in developer preview, with a hosted version expected to reach general availability in 2026.
* **Greenhouse** — 🟡 **Official (rolling out).** Greenhouse launched its MCP in May 2026, rolling out to customers starting June 2026 ([announcement](https://www.greenhouse.com/newsroom/greenhouse-launches-mcp-giving-hiring-teams-a-governed-way-to-connect-ai-tools-to-greenhouse)). Community servers also exist.
* **Workday** — 🔌 **Third-party.** Workday does not ship its own MCP server. Its Agent System of Record (ASOR) supports MCP through an Agent Gateway, but data access today goes through integration platforms such as [CData](https://www.cdata.com/drivers/workday/mcp/) or [Workato](https://www.workato.com/product-hub/mcp-monday-26-pre-built-mcp-servers-one-enterprise-platform/).
* **Unanet** — 👥 **Community.** No official server; Unanet integrates via standard APIs (Unanet Connect). One community server exists but was archived by its owner on May 12, 2026 ([repo](https://github.com/culstrup/unanet-mcp-server)).

### Historical data sources
SSA will do one-time static loads of historical data from these into the BigQuery warehouse.
* **Lever** — replaced by Greenhouse.
* **Paylocity** — replaced by Workday.

### Other data sources with sensitive data
* **Eden (Eden Workplace)** — ⛔ **None.** Eden Workplace, the ticketing/workplace tool, offers no MCP server and no public API. (The earlier eden.so link referred to an unrelated social-media research product.)
* **Gmail** — ✅ **Official.** Google-hosted remote MCP server; requires setting up a Google Cloud project / custom connector.
