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

Each certificate gives you a **validation record** (a CNAME that proves you own the name).
Copy both.

## Step 4 — Add each validation record to your DNS zone

This record lets Lightsail confirm you control the name.

Back in your `lik.navapbc.com` DNS zone (from Step 1) in the `DNS records` tab, add the 
two **validation CNAME records** from Step 3 — one per app.
- In the name/subdomain field, paste the name before `.lik.navapbc.com`
- In the value/target field, paste the Value exactly, e.g. `_424c7224….acm-validations.aws.`

Then wait. Each certificate's status flips from **Pending** to **Valid** once Lightsail
sees its record (usually minutes, up to about an hour).

## Step 5 — Attach the validated certificate to each app

On each container service's **Custom domains** section, enable the custom domain and
select its now-**Valid** certificate:

- lik-ui → `ui.lik.navapbc.com`
- lik-mcp → `mcp.lik.navapbc.com`

## Step 6 — Point each friendly name at its app

This is the record that actually routes visitor traffic (different from the validation
record in Step 4).

In your `lik.navapbc.com` DNS zone, add two **routing CNAME records**:

- `ui.lik.navapbc.com` → the lik-ui container service's default `...cs.amazonlightsail.com` address
- `mcp.lik.navapbc.com` → the lik-mcp container service's default `...cs.amazonlightsail.com` address

## Step 7 — Update the Managed Agents configuration

The lik-mcp tool is registered in the Managed Agents configuration by its URL, which may still
points at the old `...cs.amazonlightsail.com` address. Go to https://platform.claude.com/workspaces/default/agents and update all relevant agents to use the new custom domain:

- Set the lik-mcp tool URL to `https://mcp.lik.navapbc.com/mcp`


## Step 8 — Test

DNS changes are not instant — give it a few minutes after Step 6.

Open both in a browser:

- `https://ui.lik.navapbc.com`
- `https://mcp.lik.navapbc.com`

Each should load with a valid lock icon. If a name fails at first, wait a few minutes and
retry before assuming something is broken.

---

## Summary of records in the `lik.navapbc.com` zone

| Record | Type | Purpose | Points to |
|---|---|---|---|
| (validation record for ui) | CNAME | Prove domain ownership for the cert | Value given by Lightsail in Step 3 |
| (validation record for mcp) | CNAME | Prove domain ownership for the cert | Value given by Lightsail in Step 3 |
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
