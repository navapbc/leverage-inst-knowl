# Giving lik-ui and lik-mcp custom domain names (native Lightsail)

This guide points two apps at friendly HTTPS addresses using Lightsail's built-in
custom-domain feature. No Route 53 and no CloudFront required.

- **lik-ui** → `ui.lik.navapbc.com`
- **lik-mcp** → `mcp.lik.navapbc.com`

Each app runs in its own Lightsail container service and is currently only reachable
at an ugly default address like `...cs.amazonlightsail.com`. The job is to (a) get a
DNS "home" you control for `lik.navapbc.com`, and (b) in that home, point the two
friendly names at the two apps, with HTTPS.

### A few terms

- **DNS** — the phonebook that turns a name like `ui.lik.navapbc.com` into an actual server.
- **Zone** — the section of that phonebook for one domain.
- **CNAME** — a phonebook entry that says "this name is an alias for that other name."
- **Nameserver** — the specific server that holds a zone.

> **Note:** This guide is console-first because that's the simplest path for the first
> setup. Everything here can later be moved into Terraform if you want it version-controlled.

---

## Step 1 — Create a DNS zone you control for `lik.navapbc.com`

In Lightsail: **Networking → Create DNS zone → enter `lik.navapbc.com`**.

Lightsail creates the zone and shows you **4 nameserver addresses** (they look like
`ns-123.awsdns-45.com`). Copy them — you need them in the next step.

## Step 2 — Ask company IT to delegate `lik.navapbc.com` to those nameservers

`navapbc.com` is managed by company IT. Send them this request:

> Please add **NS records** for the subdomain `lik.navapbc.com` pointing to these four
> nameservers:
> - `<ns-1>`
> - `<ns-2>`
> - `<ns-3>`
> - `<ns-4>`
> This delegates the `lik.navapbc.com` sub-name to a DNS zone we manage, so we can add
> our own app records under it without further requests.

This is a **one-time** handoff. After IT does it, anything ending in `lik.navapbc.com`
is looked up in your zone, and you never need IT again for these apps.

Wait until it's live. To check from a terminal:

```
dig NS lik.navapbc.com +short
```

It should return your four nameservers.

## Step 3 — Create an HTTPS certificate for each app

A certificate is what makes browsers show `https://` with a lock instead of a warning.

> **Do not use ACM (AWS Certificate Manager) here.** Lightsail container services have
> their own certificate feature. ACM certificates will not appear as an option and cannot
> be attached to a Lightsail container service.

You need **two separate certificates** — one per app — because a certificate is attached
to the container service that serves the name, and these are two different container
services.

- On the **lik-ui** container service → **Custom domains → Create certificate** →
  enter `ui.lik.navapbc.com`.
- On the **lik-mcp** container service → **Custom domains → Create certificate** →
  enter `mcp.lik.navapbc.com`.

Each certificate needs a **validation record** (a CNAME that proves you own the name) —
but because your DNS zone lives in Lightsail in the same account (Step 1), you normally
**don't add this yourself**. See Step 4.

## Step 4 — Validation records (usually automatic)

This record lets Lightsail confirm you control the name.

**Because your `lik.navapbc.com` zone is a Lightsail DNS zone in the same account,
Lightsail adds each validation CNAME to it automatically when you create the certificate
(Step 3).** The certificate status moves from *"Attempting to validate…"* to **Valid** on
its own, usually within minutes. If that happened, there is nothing to do here — skip to
Step 5.

**Manual fallback** — only if a certificate is *not* validating automatically (this is the
required path when your DNS is hosted outside Lightsail, e.g. Route 53 or a registrar).
On the certificate, expand **Validation details** and copy the CNAME Name and Value, then
add it in your `lik.navapbc.com` DNS zone's `DNS records` tab — one per app:
- In the name/subdomain field, paste the name before `.lik.navapbc.com`
- In the value/target field, paste the Value exactly, e.g. `_424c7224….acm-validations.aws.`

You have 72 hours to add the record before the request expires. Once Lightsail sees it, the
status flips to **Valid**.

## Step 5 — Attach the validated certificate to each app

On each container service's **Custom domains** section, enable the custom domain and
select its now-**Valid** certificate:

- lik-ui → `ui.lik.navapbc.com`
- lik-mcp → `mcp.lik.navapbc.com`

> **⚠️ If the container services are managed by Terraform (they are — see `infra/`), this
> console attach creates drift.** Terraform reads the attached domain on its next refresh,
> and because the attachment lives in a `public_domain_names` block, a `terraform plan` will
> propose to **remove** it (`- public_domain_names`) unless the config declares it too.
> Applying that plan would detach your certificate.
>
> The `infra/` config already declares the attachment as a `dynamic "public_domain_names"`
> block gated on the `ui_custom_domain_url` / `mcp_custom_domain_url` variables, with
> `certificate_name` `lik-ui-prod-cert` / `lik-mcp-prod-cert`. So the fix is to **set those
> variables** (Step 7.c below) *before* the next apply — that makes the desired config match
> the console attach, and the plan drops the removal. If the console-created certificate has
> a different name than those literals, update the `.tf` to match. See
> `docs/deploy-runbook.md` "Custom-domain migration" for the full apply sequence.

## Step 6 — Point each friendly name at its app

This is the record that actually routes visitor traffic (different from the validation
record in Step 4).

In your `lik.navapbc.com` DNS zone, add two **routing CNAME records**:

- `ui.lik.navapbc.com` → the lik-ui container service's default `...cs.amazonlightsail.com` address
- `mcp.lik.navapbc.com` → the lik-mcp container service's default `...cs.amazonlightsail.com` address

> **Where to find that address:** on the container service's page, the console labels it
> **Public domain** (e.g. `lik-ui-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com`) —
> distinct from **Custom domains** (the friendly names you attached) and **Private domain**
> (internal only). Paste it as a **bare hostname**: no `https://`, no trailing `/`. Heads-up
> on a naming clash: the Terraform/API field `publicDomainNames` holds the *custom* domains,
> the opposite of the console's "Public domain" label — hence this guide says "default
> address" throughout.

## Step 7 — Point the app configuration at the friendly domains

The certificate and DNS work above only changes how the apps are *reached*. Three places
still reference the old `...cs.amazonlightsail.com` addresses and must be updated to the new
friendly domains, or logins and data-source connections will break.

### Step 7.a — Update the Managed Agents configuration

The lik-mcp tool is registered in the Managed Agents configuration by its URL, which may
still point at the old `...cs.amazonlightsail.com` address. Go to
https://platform.claude.com/workspaces/default/agents and update all relevant agents:

- Set the lik-mcp tool URL to `https://mcp.lik.navapbc.com/mcp`

### Step 7.b — Update each OAuth client's registered redirect (callback) URL

Every OAuth provider only redirects back to a **pre-registered** callback URL. lik-ui uses
two callback paths, both under its own friendly domain (`ui.lik.navapbc.com`):

- **App login** (Google OIDC) → `https://ui.lik.navapbc.com/auth/callback`
- **Data-source connections** (GitHub, Google Drive, lik-mcp) → `https://ui.lik.navapbc.com/connections/callback`

In each provider's OAuth app settings, **add** the new URL to the allowed redirect/callback
list (keep the old one until cutover is confirmed, then remove it):

- **Google app-login client** → add the `/auth/callback` URL above.
- **GitHub OAuth App** → set/add the `/connections/callback` URL as the Authorization callback URL.
- **Google Drive client** and **lik-mcp client** → add the `/connections/callback` URL.
- **Atlassian** → nothing to register by hand: it uses Dynamic Client Registration, so lik-ui
  re-registers the redirect URL automatically on the next connect (it registers whatever
  `redirect_uri` lik-ui is currently configured with — see Step 7.c). If a stale client was
  registered under the old domain, just reconnect Atlassian after 7.c to refresh it.

Also update any **resource URLs** that point at lik-mcp's old address so they use the friendly
domain (these key the stored credential and must match exactly on both sides):

- lik-ui: `LIK_UI_LIKMCP_RESOURCE_URL=https://mcp.lik.navapbc.com/mcp`
- lik-mcp: `LIK_RESOURCE_SERVER_URL=https://mcp.lik.navapbc.com/mcp`

Because the resource URL is the vault credential key, users may need to **reconnect** lik-mcp
once after this change.

### Step 7.c — Update the callback URL lik-ui itself sends

lik-ui builds both callback URLs from a single setting — it does **not** hardcode them. Point
that setting at the friendly domain and redeploy:

- Set `LIK_UI_APP_BASE_URL=https://ui.lik.navapbc.com`

On the next deploy, lik-ui sends `https://ui.lik.navapbc.com/auth/callback` and
`.../connections/callback` — which must match what you registered in Step 7.b. (This same
value is what Atlassian's DCR will register, closing the loop for that source.)

> **In the Terraform deployment (`infra/`), you do not set `LIK_UI_APP_BASE_URL` (or the
> lik-mcp resource URL) by hand.** They are derived from the `ui_custom_domain_url` /
> `mcp_custom_domain_url` variables, because the container service's `.url` attribute always
> returns the default `...cs.amazonlightsail.com` address even after the custom domain is
> attached. Set those two variables via `-var` on `./tf.sh apply`; that single
> change drives all the URL-derived env values *and* keeps the `public_domain_names`
> attachment from Step 5 under management. See `infra/README.md` "URL-derived env values and
> custom domains" and `docs/deploy-runbook.md`.


## Step 8 — Test

DNS changes are not instant — give it a few minutes after Step 6.

Open both in a browser:

- `https://ui.lik.navapbc.com`
- `https://mcp.lik.navapbc.com`

Each should load with a valid lock icon. If a name fails at first, wait a few minutes and
retry before assuming something is broken.

---

## Caveat: real-time streaming and timeouts

Both apps stream responses over **SSE** (`text/event-stream`): lik-ui streams chat tokens,
and lik-mcp uses the MCP streamable-http transport (SSE under the hood). Two things to know
when putting them behind a custom domain:

- **Keep the routing records pointing *directly* at the container service (as Step 6 does).
  Do NOT insert a Lightsail distribution / CDN in front of these apps.** A Lightsail
  distribution has a 30-second origin-response timeout and only handles
  `Transfer-Encoding: chunked`, which breaks longer SSE streams.
- **The container-service ingress has a fixed, undocumented, non-configurable timeout.** A
  long stream (e.g. a lengthy LLM generation or a slow MCP tool call) can be cut mid-response
  with a 504-class error, and there is no knob to raise the ceiling. If long streams die
  mid-response, suspect the ingress timeout first — not the app code.
- **Scaling fallback:** if reliable long-lived streaming becomes a hard requirement, the
  managed Lightsail ingress is the wrong tier — move to ECS/EC2 behind an ALB, where the
  idle timeout is configurable. See the apps' READMEs for the tracked TODO.

## Summary of records in the `lik.navapbc.com` zone

| Record | Type | Purpose | Points to |
|---|---|---|---|
| (validation record for ui) | CNAME | Prove domain ownership for the cert | Auto-added by Lightsail at cert creation (Step 4); manual only if auto-validation fails |
| (validation record for mcp) | CNAME | Prove domain ownership for the cert | Auto-added by Lightsail at cert creation (Step 4); manual only if auto-validation fails |
| `ui.lik.navapbc.com` | CNAME | Route traffic to lik-ui | lik-ui default `...cs.amazonlightsail.com` |
| `mcp.lik.navapbc.com` | CNAME | Route traffic to lik-mcp | lik-mcp default `...cs.amazonlightsail.com` |

The NS delegation from Step 2 lives in company IT's `navapbc.com` zone, not this one.

---

## Alternative: for people already using Terraform

The console guide above is the recommended path for a first-time or one-off setup —
every step is a click with visible feedback. This section is for someone **already
comfortable with Terraform** who wants the setup version-controlled and repeatable across
future apps. It is not simpler for a novice: it has fewer steps only because the work is
compressed into `terraform apply`, and it assumes you can write HCL, read Terraform state,
and drop to the AWS CLI when needed.

Verified against provider **hashicorp/aws 6.54.0**.

> **⚠️ The one trap that will waste your afternoon:** container-service certificates are
> **not** the `aws_lightsail_certificate` resource. That resource is a *different,
> non-interchangeable* certificate type (for Lightsail load balancers / distributions).
> Pointing a container service at one silently fails. The certificate for a container
> service is declared **inside** the container service, in the nested
> `public_domain_names.certificate` block shown below.

### What Terraform can and cannot do here

| Console step | In Terraform? | Notes |
|---|---|---|
| 1. Create DNS zone | ⚠️ Partial | `aws_lightsail_domain` creates it, but does **not** export the nameservers — read the 4 NS from the console to give IT. |
| 2. IT delegation | ❌ No | External human process. |
| 3. Create per-app certificate | ✅ Yes | The `public_domain_names.certificate` block — **not** `aws_lightsail_certificate`. |
| 4. Add validation records | ⚠️ Partial | The block does **not** export the validation record values. Read them via `aws lightsail get-certificates`, then place them as `aws_lightsail_domain_entry`. |
| 5. Attach certificate | ✅ Yes* | Same block. *Known flakiness — if the cert shows attached but TLS fails, fall back to `aws lightsail update-container-service`. |
| 6. Routing CNAME records | ✅ Yes | `aws_lightsail_domain_entry`; reference the service's exported `url`. |
| 7. Test | ❌ No | Manual. |

### The realistic flow: two applies with a manual bridge

Because the validation record *values* aren't exposed as outputs (Step 4), you cannot do
this in a single apply. It becomes:

1. **`terraform apply` #1** — create the DNS zone and the container service with its
   certificate block (certificate status becomes "pending").
2. **Manual bridge** —
   - Read the 4 nameservers from the console and send them to IT (Step 2); wait for delegation.
   - Read the certificate's validation record values: `aws lightsail get-certificates`.
3. **`terraform apply` #2** — add the validation records and the routing records (now that
   you know the values). Wait for the certificate to validate and attach; use the CLI
   fallback above if attachment misbehaves.
4. **Manual** — test both URLs in a browser.

### Sketch of the resources (per app)

```hcl
# Step 1 — the DNS zone (nameservers not exported; read from console)
resource "aws_lightsail_domain" "lik" {
  domain_name = "lik.navapbc.com"
}

# Steps 3 + 5 — cert declared INSIDE the container service (not aws_lightsail_certificate)
resource "aws_lightsail_container_service" "ui" {
  name  = "lik-ui"
  power = "nano"   # match your existing service
  scale = 1

  public_domain_names {
    certificate {
      certificate_name = "lik-ui-cert"
      domain_names     = ["ui.lik.navapbc.com"]
    }
  }
}

# Step 4 — validation record (VALUE comes from `aws lightsail get-certificates`, added in apply #2)
resource "aws_lightsail_domain_entry" "ui_validation" {
  domain_name = aws_lightsail_domain.lik.domain_name
  name        = "<validation record name from CLI>"
  type        = "CNAME"
  target      = "<validation record value from CLI>"
}

# Step 6 — routing record pointing the friendly name at the service
resource "aws_lightsail_domain_entry" "ui_routing" {
  domain_name = aws_lightsail_domain.lik.domain_name
  name        = "ui.lik.navapbc.com"
  type        = "CNAME"
  target      = trimsuffix(trimprefix(aws_lightsail_container_service.ui.url, "https://"), "/")
}
```

Repeat the container-service, validation, and routing resources for `lik-mcp` /
`mcp.lik.navapbc.com`. The `aws_lightsail_domain` zone is shared by both apps.

> **If full end-to-end automation matters more than staying on native Lightsail**, the
> CloudFront + ACM + Route 53 path automates in essentially a single `terraform apply`:
> `aws_acm_certificate` exposes its validation records, which chain directly into
> `aws_route53_record` with no manual bridge. That is the pattern our other app already
> uses. The trade-off is more moving parts (a CloudFront distribution per app).
