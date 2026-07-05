# Go To Market and Monetisation

A step by step plan to turn SiteBot into revenue. Numbers are illustrative
starting points; adjust to your market and validate with real pricing tests.

## 1. The market and how to win in it

Website chatbots are a crowded category. Competing on being "a chatbot" loses.
Win on a sharp wedge and a specific buyer outcome.

Differentiation angles, pick two:

- Instant proof. A prospect enters their URL and gets a live, working bot on
  their own content in about two minutes. This is the single strongest sales
  asset and your top-of-funnel loop.
- Grounded and cited answers. Every answer links to the source page. Position as
  "answers you can trust, with receipts," against generic bots that hallucinate.
- Done for you setup. You configure, test, and hand over a working bot. This fits
  a consulting-led motion and commands setup fees.
- Data residency and control. Host in an India region or the customer's own
  cloud. Strong for regulated and privacy-conscious buyers.
- Agency and white-label. Let agencies resell it under their brand to their own
  client base. This multiplies reach without multiplying your sales effort.

## 2. Ideal customer profiles

Target sites that are content rich and carry a support or sales-answer load.

| Segment | Why they buy | Value metric they feel |
| --- | --- | --- |
| B2B SaaS (small and mid) | Deflect support tickets, help trials self-serve | Tickets deflected, activation |
| E-commerce and D2C | Answer product, shipping, returns questions | Conversion, fewer "where is my order" tickets |
| Professional services (law, accounting, clinics) | Answer FAQs, qualify and capture leads | Leads captured, fewer phone calls |
| Real estate | Property and process questions, capture buyer intent | Qualified leads |
| Education and edtech | Course, admission, and fee questions | Enrolment inquiries handled |
| Agencies (web, marketing) | Add an AI upsell to client retainers | New recurring revenue per client |

Start with one or two verticals so your demos, case studies, and prompt tuning
compound. Agencies are a force multiplier and worth a dedicated track.

## 3. Packaging and pricing

Value metric: messages answered per month, with resolved conversations as the
story you sell (support cost saved, leads captured). Keep tiers simple.

| Plan | Price (monthly) | Sites | Messages/mo | Key limits and features |
| --- | --- | --- | --- | --- |
| Free | 0 | 1 | ~100 | SiteBot branding, limited pages, no integrations. Acquisition tier. |
| Starter | 39 to 49 | 1 | ~2,000 | Remove branding at this tier or the next, email support, basic analytics. |
| Growth | 129 to 199 | 3 | ~10,000 | Lead capture, full analytics, unanswered-questions report, integrations. |
| Business | 399 to 699 | 10 | ~40,000 | White-label, priority support, human handoff, SSO on request. |
| Enterprise | Custom | Unlimited | Custom | Data residency, VPC or on-prem, SLA, DPA, dedicated support. |

Add-ons and levers:

- Usage overage: a set price per additional 1,000 messages, billed automatically.
- Setup and onboarding fee: 200 to 2,000 one time for done-for-you configuration.
  This funds your time and filters for serious buyers.
- White-label and agency: a higher base plus a per-client fee, or a revenue share.
  Agencies happily pay for a branded, ready-to-resell product.
- Annual billing: offer two months free for annual prepay to improve cash and
  reduce churn.

Anchoring: price against the cost of the problem, not against other bots. One
support agent, or a handful of lost leads per month, dwarfs these prices. Lead
with the savings, then the price.

## 4. Unit economics

Cost of goods per answered message is one embedding of the question plus one LLM
completion over retrieved context. With a small embedding model and a Haiku-tier
answer model, this is on the order of a cent or less per message. Illustrative:

| Item | Assumption | Monthly cost |
| --- | --- | --- |
| Messages | 5,000 | reference volume |
| Cost per message | ~0.005 to 0.01 USD | blended embedding + answer |
| LLM and embedding COGS | | ~25 to 50 USD |
| Vector store and hosting share | small VM + Postgres | ~10 to 30 USD |
| Total COGS at this volume | | ~35 to 80 USD |
| Plan price (Growth) | | 129 to 199 USD |
| Gross margin | | roughly 60 to 80 percent, rising with scale |

Targets to hold:

- Gross margin: 75 percent or higher at steady state. Use answer caching and
  smaller models for easy questions to protect it.
- CAC payback: under 6 months for self-serve, under 12 for sales-led.
- LTV to CAC: 3 or higher. Improve LTV with annual plans, add-on sites, and the
  lead-capture ROI story that makes churn painful for the customer.

## 5. The sales motion, step by step

Run product-led growth for volume and a light sales-led track for larger deals.

Product-led (self-serve):

1. Prospect lands on your site or sees a demo, enters their URL.
2. The instant-demo generator crawls a subset of their site and returns a live
   bot link within minutes.
3. They try it on their own content. This is the "aha" moment.
4. Prompt to sign up for a free account to keep the bot and get the embed snippet.
5. In-app nudges drive activation: install the widget, invite a teammate, see
   analytics. Trigger an upgrade prompt when they hit the free message cap or want
   to remove branding, add a site, or capture leads.

Sales-led (for Growth and above):

1. Outbound with a personalised, working demo, not a cold pitch. Pre-generate a
   bot on the prospect's site and send the link. Reply rates jump when the first
   message already shows value.
2. A short call to confirm the use case, the volume, and the buyer.
3. A time-boxed pilot on their real site with a success metric agreed up front
   (for example deflection rate or leads captured in two weeks).
4. Convert the pilot to an annual plan. Offer done-for-you setup to remove friction.

Agency track:

1. Identify web and marketing agencies serving your target verticals.
2. Offer a white-label plan and a partner margin or revenue share.
3. Give them a one-page sell sheet and a demo they can run on any client site.
4. Support their first two client deployments closely to create references.

## 6. The instant-demo growth loop (highest leverage)

Build a public page where anyone enters a URL and gets a working bot in minutes.
This is your best acquisition, sales, and virality engine at once.

- Acquisition: the demo itself is the ad. Shareable and self-explanatory.
- Sales: every outbound message can carry a live bot on the prospect's own site.
- Virality: the demo bot carries a subtle "powered by SiteBot" that links back.

Guardrails: cap pages and messages for anonymous demos to control cost, expire
demo bots after a period, and require the person to confirm they are authorised to
index the site. Convert demos to accounts with a clear call to action.

## 7. Leveraging your LinkedIn audience

You have a large, relevant following. Turn it into a distribution advantage.

- Build in public. Post the journey: crawling and grounding, a real deflection
  number, a before-and-after of a client bot. Show, do not tell.
- Lead magnets. Offer a free bot for the first N commenters or a teardown of their
  site's FAQ. Each teardown is a warm demo.
- Case studies. Publish one concrete result per customer: tickets deflected, leads
  captured, hours saved. Two or three strong case studies close far more than any
  feature list.
- Direct outreach. When someone engages, send them a pre-built bot on their site
  by direct message. Personalised and instant.
- Weekly cadence. One substantive post and a handful of tailored demos per week
  compounds quickly with an engaged audience.

## 8. Onboarding and activation

Time to value is the whole game. Define activation as: site indexed and widget
installed and at least one real question answered well.

- Reduce steps: URL in, crawl runs, snippet out. Offer to install the snippet for
  them via a short guide per platform (WordPress, Shopify, Webflow, custom).
- Confirm quality: after indexing, show three sample questions and answers so the
  customer immediately trusts it.
- Nudge the ROI features early: turn on lead capture and analytics in the first
  session so the value is visible from day one.

## 9. Retention and expansion

- Analytics and the unanswered-questions report make the product a content and
  support strategy tool, not just a widget. This is sticky.
- Lead capture creates a hard-to-cancel ROI: cancelling means losing a lead
  source. Report leads and estimated pipeline value monthly.
- Expansion paths: add more sites, higher message tiers, white-label, integrations,
  and multilingual. Prompt upgrades at natural limits.
- Quarterly value review for larger accounts: show deflection, leads, and savings,
  then propose the next tier.

## 10. Metrics to run the business

| Metric | Definition | Why |
| --- | --- | --- |
| Activation rate | Accounts that reach indexed + installed + answered | Predicts retention |
| Deflection rate | Conversations resolved without human help | Core customer ROI |
| Leads captured | Emails or intents captured per site | The expansion and retention lever |
| Messages per site | Usage and engagement | Health and upsell signal |
| MRR and net revenue retention | Recurring revenue and expansion minus churn | The scoreboard |
| Gross churn | Cancelled accounts per month | Watch closely under 100 MRR plans |
| CAC and payback | Cost to acquire and months to recover it | Keeps growth efficient |
| Cost per message | LLM plus embedding plus infra per message | Protects gross margin |

## 11. Ninety-day launch plan

| Weeks | Focus | Concrete outcomes |
| --- | --- | --- |
| 1 to 2 | Harden and dogfood | Phase 1 essentials; run SiteBot on your own site and three friendly sites; write the first teardown post |
| 3 to 4 | Instant demo and free tier | Ship the public URL-to-bot demo; open free signups; add basic analytics and lead capture |
| 5 to 6 | First paying customers | Personalised outbound with live demos; land three to five design partners on Starter or Growth with a pilot metric |
| 7 to 8 | Proof and content | Publish two case studies with real numbers; refine onboarding to cut time to value |
| 9 to 10 | Monetise properly | Add Stripe billing, overages, and annual plans; introduce setup fees for done-for-you |
| 11 to 12 | Leverage and scale | Launch white-label and an agency partner track; sign the first one or two agencies; set targets for the next quarter |

Target by day 90: a repeatable instant-demo loop, five to fifteen paying
customers, two case studies, billing automated, and at least one agency partner in
motion.

## 12. Legal, compliance, and trust essentials

- Authorisation to index. Require customers to confirm they own or are authorised
  to index each site. Put it in the terms of service and as a signup checkbox.
  Honour robots.txt, which the crawler already does.
- Data processing agreement. Offer a DPA. State what is stored, where, and for how
  long. Provide a deletion path.
- Data residency. Offer an India region and, as demand appears, an EU region.
- PII handling. Add an option to redact captured personal data and to disable
  conversation storage for sensitive customers.
- Clear refund and cancellation terms. Reduce friction to buy and to trust.

## 13. Risks and moats

- Risk: commoditisation and price pressure. Moat: vertical depth, the
  unanswered-questions and lead-capture ROI, and agency distribution.
- Risk: answer quality complaints. Moat: strict grounding, citations, confidence
  thresholds, and a per-vertical evaluation set.
- Risk: rising model costs. Moat: caching, model routing, and pricing tied to
  value rather than raw usage.
- Risk: platform dependence on one model provider. Mitigation: the provider seam
  in the code lets you switch or blend models.
