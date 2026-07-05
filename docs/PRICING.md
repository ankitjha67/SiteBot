# Monetization & Pricing Recommendation

Short answer: **subscription (SaaS), not one-time — with a setup fee and an
agency/white-label track on top.** One-time selling caps your revenue and leaves
you carrying ongoing model + hosting costs with no recurring income. SiteBot's
own unit economics (a cent or less per answered message) are built for
recurring, usage-tiered pricing.

## Why subscription over one-time

| | Subscription (recommended) | One-time sale |
| --- | --- | --- |
| Your ongoing cost (model + hosting per message) | Covered by recurring revenue | You keep paying after you're paid once |
| Revenue per customer | Compounds; expands with usage/seats/sites | Capped at the sale |
| Churn signal / relationship | You see usage, can save & upsell | You lose contact after delivery |
| Valuation (if you ever sell the business) | 4–8× ARR | ~1× revenue |
| Buyer expectation for a hosted AI tool | Normal, expected | Unusual; implies self-host |

**One-time is only right for two cases:** (1) a **self-hosted license** for an
enterprise that must run it in their own VPC/on-prem (price it high — see below),
and (2) **done-for-you setup**, sold as a one-time fee *on top of* a subscription.

## Recommended model: tiered SaaS + setup fee + agency track

The market comparables (Chatbase, SiteGPT, CustomGPT, Chatwoot) price on
**messages answered per month** and number of sites/seats. SiteBot matches or
exceeds their features (see `FEATURE_PARITY.md`), so price in the same band with
a security/voice/local-model edge as the differentiator.

### Core tiers (monthly; ~2 months free on annual)

| Plan | Price/mo | Sites | Messages/mo | Highlights |
| --- | ---: | --- | --- | --- |
| **Free** | $0 | 1 | ~100 | SiteBot branding, acquisition tier, self-serve |
| **Starter** | $39–49 | 1 | ~2,000 | Remove branding, email support, basic analytics |
| **Growth** | $129–199 | 3 | ~10,000 | Lead capture, full analytics, unanswered report, all channels, AI Actions |
| **Business** | $399–699 | 10 | ~40,000 | White-label, Secrets Guardian, voice, priority support, team roles, SSO on request |
| **Enterprise** | Custom (from ~$1,500/mo) | Unlimited | Custom | Self-host/VPC, data residency, SLA, DPA, dedicated support |

These are anchored to real comparables: SiteGPT runs $39 / $79 / $259, Chatbase
Starter is ~$40 and scales to $500+. Land in that range; don't undercut to the
floor — your security (Secrets Guardian), voice, and local-model/offline story
justify the middle-to-upper band.

### Add-ons & levers (this is where margin compounds)

- **Usage overage**: a set price per additional 1,000 messages (e.g. $5–10),
  billed automatically. SiteBot already meters `usage_events`.
- **Setup / done-for-you fee**: $200–$2,000 one-time to configure, index, tune,
  and hand over a working bot. Funds your time and filters serious buyers.
- **White-label / agency**: higher base + a per-client fee (e.g. $299/mo base +
  $25–49 per deployed client), or a revenue share. Agencies happily pay for a
  branded, ready-to-resell product — this is your highest-leverage channel.
- **Self-hosted enterprise license**: if a customer must run it in their own
  infra, price it as an **annual license** ($10k–$50k/yr depending on size)
  *plus* support — not a true one-time, because they'll want updates and help.
- **Annual billing**: 2 months free for annual prepay; improves cash and cuts churn.

## What to charge — the one-line recommendation

- **Solo founder / indie SaaS play:** Free → $49 → $149 → $499, message-metered,
  with a $299 optional setup fee. Simple, comparable to the market, healthy margin.
- **Agency / services play:** lead with **done-for-you** ($500–$2,000 setup) +
  a $99–$199/mo retainer per client, or the white-label base + per-client model.
  This monetizes fastest because you're selling outcomes, not software.
- **Enterprise/regulated inbound:** custom from ~$1,500/mo hosted, or a
  $10k–$50k/yr self-hosted license — the Secrets Guardian, data residency, and
  local-model/offline operation are exactly what these buyers pay a premium for.

## Pricing principle

Anchor to the **cost of the problem, not to other bots**. One support agent, or
a handful of lost leads a month, dwarfs these prices. Lead with the savings
(tickets deflected, leads captured, hours saved — all visible in Analytics),
then the price. Keep the free tier as the acquisition loop and let usage limits,
branding removal, extra sites, and lead capture drive upgrades.

See `GTM_MONETIZATION.md` for the full go-to-market motion, ICPs, and 90-day
launch plan.
