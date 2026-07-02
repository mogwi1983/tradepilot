# TradePilot — Lead Intelligence Platform for Licensed Trades

## What This Is

TradePilot is a standalone SaaS platform that produces verified, mail-ready prospect lists
for anyone who wants to reach licensed trade contractors — HVAC, plumbing, electrical,
roofing, and others — based on their digital presence profile and license data.

It answers a question that nobody has cleanly solved:

> "Give me a list of active HVAC contractors in my metro area who have no website,
> have a Facebook page, and have a verified mailing address I can actually use."

That question sounds simple. Getting a trustworthy answer to it is not.
TradePilot is the infrastructure that makes that answer reliable.

---

## Why This Exists

The immediate use case is TradeDraftAI, a proposal automation SaaS for small HVAC
contractors. TradeDraftAI's go-to-market strategy depends on direct mail to contractors
who have no digital systems — because those are the contractors with no existing SaaS
tool to switch away from.

Finding those contractors requires:

1. A public licensing database (TDLR in Texas, equivalent agencies in other states)
2. Digital presence detection — does this contractor have a website? A Facebook page?
3. Address resolution — can we find a real, USPS-deliverable mailing address?
4. Address validation — is the address deliverable before we spend money on a mailer?

The first attempt at this workflow (outsourced to an AI agent) failed because:
- No addresses exist in the raw TDLR export
- The agent had no structured retry logic and gave up after weak attempts
- Paid enrichment tools were used without gates, wasting budget
- The output was 5 usable records from a 1,666-record input

TradePilot is the disciplined rebuild of that workflow — structured as phases,
auditable at every step, cost-controlled by design.

---

## Why This Is a SaaS Opportunity

Anyone trying to reach licensed contractors for B2B sales faces the same problem:
- Public licensing data exists but contains no contact information
- Commercial contact databases are expensive, stale, and generic
- Digital presence filtering (website yes/no, Facebook yes/no) does not exist anywhere
- Address verification at scale requires infrastructure most small operators don't have

TradePilot solves all of these in one pipeline:

1. Ingest any state's contractor licensing export
2. Detect digital presence (website, Facebook, GBP, directories)
3. Resolve mailing addresses through a tiered free-to-paid search ladder
4. Validate addresses via USPS (Lob API)
5. Classify prospects by digital profile and deliver verified, segmented lists

Target buyers:
- SaaS companies targeting trades (proposal tools, scheduling software, CRM)
- Marketing agencies running direct mail for B2B clients
- Franchise development teams targeting owner-operators
- Insurance and financing companies targeting licensed small businesses
- Anyone running a targeted outreach campaign who cannot afford to mail blindly

---

## Current Scope (MVP)

State: Texas
Licensing source: TDLR (Texas Department of Licensing and Regulation)
Initial trade: HVAC (A/C Contractors)
Initial geography: 6 counties — Tarrant, Dallas, Denton, Collin, Johnson, Ellis
Initial segments: Batch 1 (no web, no FB) and Batch 2 (no web, has FB)
Initial consumer: TradeDraftAI

---

## Future Scope

- Additional Texas trades: plumbing, electrical, roofing
- Additional states: any state with a public licensing database
- Self-serve web interface: natural-language list request, automated delivery
- Webhook delivery: push verified lists directly to CRM or mail platform
- Scheduled refresh: re-run lists on a cadence to catch new licenses and status changes

---

## What This Project Is Not

- This is not part of the TradeDraftAI codebase or repository
- This is not a marketing tool owned by TradeDraftAI
- TradeDraftAI is a customer of TradePilot, not the owner of it
- This project should be architected as if TradeDraftAI were one of many clients

