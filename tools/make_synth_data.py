#!/usr/bin/env python3
"""Deterministic synthetic support-ticket data generator.

Stdlib only. Run as: python3 tools/make_synth_data.py (from repo root).
Writes data/synthetic/support_tickets_synth_v1.jsonl and self-validates
every record against the schema contract in schema/ticket.schema.json
(structurally re-implemented here, no external jsonschema dependency).
"""
import json
import os
import random
import re
import sys

SEED = 20260928
RNG = random.Random(SEED)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_PATH = os.path.join(REPO_ROOT, "data", "synthetic", "support_tickets_synth_v1.jsonl")

CHANNELS = ["email", "web_form", "chat", "api"]
TIERS = ["free", "pro", "enterprise"]
PRODUCT_AREAS = ["api", "dashboard", "billing_portal", "mobile", "webhooks", "data_export", "auth", "unknown"]

TICKET_ID_RE = re.compile(r"^TCK-[0-9]{4}$")
CUSTOMER_ID_RE = re.compile(r"^C-[0-9]{4}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

ROUTE_ENUM = {"billing", "technical_bug", "escalation", "faq"}
PRIORITY_ENUM = {"low", "medium", "high", "critical"}
AMBIGUITY_ENUM = {"clear", "ambiguous", "insufficient_info"}
CHANNEL_ENUM = set(CHANNELS)
TIER_ENUM = set(TIERS)
PRODUCT_AREA_ENUM = set(PRODUCT_AREAS)


def mk(idx, created_at, channel, cust_id, tier, since, subject, body,
       route, priority, requires_human, ambiguity, rationale,
       metadata=None):
    ticket = {
        "ticket_id": "TCK-%04d" % idx,
        "created_at": created_at,
        "channel": channel,
        "customer": {"id": cust_id, "tier": tier, "since": since},
        "subject": subject,
        "body": body,
        "expected": {
            "route": route,
            "priority": priority,
            "requires_human": requires_human,
            "ambiguity": ambiguity,
            "rationale": rationale,
        },
    }
    if metadata is not None:
        ticket["metadata"] = metadata
    return ticket


def build_tickets():
    tickets = []

    # ---------------- BILLING (6) ----------------
    tickets.append(mk(
        1, "2026-09-02T14:12:03Z", "email", "C-1042", "pro", "2024-03-11",
        "Refund request for accidental annual upgrade",
        "Hi team, I ment to click monthly but it charged me for the annual "
        "plan instead ($480). Can you please refund the difference back to "
        "my card? Order id was placed yesterday around 3pm. Thanks, appreciate "
        "the quick help as always.",
        "billing", "medium", False, "clear",
        "Straightforward accidental-upgrade refund request with clear order timing and amount; no ambiguity in intent.",
        {"product_area": "billing_portal", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        2, "2026-09-03T09:45:11Z", "web_form", "C-2087", "free", "2025-01-20",
        "want refund pls",
        "i cancelled last week but still got billed 12 dollars, i want my money back asap this isnt fair",
        "billing", "low", False, "clear",
        "Simple duplicate-billing-after-cancellation refund request with a small amount; low priority, clearly billing.",
        {"product_area": "billing_portal", "previous_tickets_30d": 1, "has_attachments": False},
    ))
    tickets.append(mk(
        3, "2026-09-04T18:03:44Z", "email", "C-3311", "enterprise", "2022-06-01",
        "Double charge on enterprise invoice #INV-88213",
        "Our finance team flagged that invoice INV-88213 for $4,800 was "
        "charged twice to our corporate card on the same day (Sept 1st). "
        "Here is the export from our banking portal:\n\n"
        "```csv\n"
        "date,description,amount\n"
        "2026-09-01,ACME SUPPORT SOFTWARE,4800.00\n"
        "2026-09-01,ACME SUPPORT SOFTWARE,4800.00\n"
        "2026-08-01,ACME SUPPORT SOFTWARE,4800.00\n"
        "```\n"
        "Please confirm this is a duplicate charge and process a refund for one of the two September lines. "
        "This is time sensitive since our monthly close is Friday.",
        "billing", "high", False, "clear",
        "Duplicate charge confirmed by bank export CSV evidence; enterprise tier with a deadline raises priority but stays a billing fix, not an escalation.",
        {"product_area": "billing_portal", "previous_tickets_30d": 0, "has_attachments": True},
    ))
    tickets.append(mk(
        4, "2026-09-05T11:20:00Z", "chat", "C-1587", "pro", "2023-11-09",
        "Confused about VAT on my last invoice",
        "hey, quick q - my invoice this month shows a VAT line for 20% but "
        "last month it didnt have one at all. did something change with tax "
        "rules or is this a mistake? we're based in Germany if that matters. "
        "just want to understand before i forward this to our accountant",
        "billing", "low", False, "clear",
        "General invoice/VAT explanation question with no urgency; customer wants clarification, not a fix.",
        {"product_area": "billing_portal", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        5, "2026-09-06T20:55:29Z", "email", "C-4423", "pro", "2024-07-22",
        "Proration math looks off after upgrading mid-cycle",
        "I upgraded from Starter to Pro on the 15th (halfway through my "
        "billing cycle) and expected to be charged roughly half the "
        "difference, but I was charged the full new-plan price plus a "
        "small credit that doesn't add up. Here's the line-item breakdown "
        "from my invoice JSON export:\n\n"
        "```json\n"
        "{\n"
        "  \"invoice_id\": \"inv_synth_5521\",\n"
        "  \"lines\": [\n"
        "    {\"desc\": \"Pro plan (full month)\", \"amount\": 4900},\n"
        "    {\"desc\": \"Starter plan credit (partial)\", \"amount\": -1200}\n"
        "  ],\n"
        "  \"total\": 3700\n"
        "}\n"
        "```\n"
        "Could someone walk me through how the proration was calculated for "
        "my account? I don't think it's wrong, I just can't reconcile the "
        "numbers myself and want to make sure I wasn't overcharged before I "
        "approve next month's budget with my manager.",
        "billing", "medium", False, "clear",
        "Customer disputes/questions proration calculation after a plan change; needs a billing explanation, not urgent.",
        {"product_area": "billing_portal", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        6, "2026-09-07T08:14:52Z", "api", "C-5560", "enterprise", "2021-02-14",
        "Card payment failing repeatedly for renewal",
        "Our automated renewal payment has failed 3 times this week. Error "
        "returned by the gateway:\n\n"
        "```json\n"
        "{\n"
        "  \"error\": {\n"
        "    \"code\": \"card_declined\",\n"
        "    \"decline_code\": \"insufficient_funds\",\n"
        "    \"charge_id\": \"ch_synth_7788221\",\n"
        "    \"amount\": 120000,\n"
        "    \"currency\": \"usd\"\n"
        "  }\n"
        "}\n"
        "```\n"
        "We believe the card on file is fine and has funds, so this looks "
        "like it could be a gateway issue on your end rather than ours. Our "
        "service risks suspension in 48 hours if this isn't resolved - please "
        "escalate to billing ops urgently, we cannot lose access.",
        "billing", "critical", True, "clear",
        "Enterprise account facing imminent service suspension from a failed renewal payment; needs urgent human billing-ops intervention.",
        {"product_area": "billing_portal", "previous_tickets_30d": 2, "has_attachments": False},
    ))

    # ---------------- TECHNICAL_BUG (8) ----------------
    tickets.append(mk(
        7, "2026-09-08T03:22:10Z", "api", "C-6001", "pro", "2023-05-18",
        "App crashes on startup after latest SDK update",
        "Updated to SDK v3.4.1 this morning and now the app crashes "
        "immediately on launch. Here's the stack trace:\n\n"
        "```\n"
        "Traceback (most recent call last):\n"
        "  File \"main.py\", line 12, in <module>\n"
        "    app.start()\n"
        "  File \"sdk/core.py\", line 88, in start\n"
        "    self._init_session(config)\n"
        "  File \"sdk/core.py\", line 140, in _init_session\n"
        "    raise SessionInitError(\"missing api_version field\")\n"
        "sdk.core.SessionInitError: missing api_version field\n"
        "```\n"
        "Rolling back to v3.3.9 fixes it. Please advise if this is a known regression.",
        "technical_bug", "high", False, "clear",
        "Clear regression with a reproducible stack trace tied to a specific SDK version bump; needs engineering triage.",
        {"product_area": "api", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        8, "2026-09-09T16:47:33Z", "web_form", "C-6112", "free", "2025-04-02",
        "Mobile app keeps crashing when opening reports tab",
        "Every time i tap on the reports tab in the mobile app it force "
        "closes. happens on both wifi and cellular. heres the crash log "
        "from my phone:\n\n"
        "```\n"
        "FATAL EXCEPTION: main\n"
        "java.lang.NullPointerException: Attempt to invoke virtual method "
        "'java.util.List com.acme.Report.getRows()' on a null object reference\n"
        "    at com.acme.reports.ReportsFragment.onViewCreated(ReportsFragment.java:74)\n"
        "    at androidx.fragment.app.Fragment.performViewCreated(Fragment.java:3121)\n"
        "```\n"
        "device is a pixel 7, app version 5.2.0. please help this is annoying",
        "technical_bug", "medium", False, "clear",
        "Reproducible mobile crash with a clear stack trace and device/version info; standard bug triage, not urgent.",
        {"product_area": "mobile", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        9, "2026-09-10T12:05:00Z", "api", "C-6220", "enterprise", "2020-09-30",
        "Recurring HTTP 500 on /v2/orders endpoint",
        "We're seeing intermittent 500s on /v2/orders, roughly 1 in every 20 "
        "requests over the past 6 hours. Sample response body:\n\n"
        "```json\n"
        "{\n"
        "  \"status\": 500,\n"
        "  \"error\": \"internal_server_error\",\n"
        "  \"request_id\": \"req_synth_99a21c\",\n"
        "  \"trace\": \"OrdersService.fetch -> DBPool.acquire -> timeout after 3000ms\"\n"
        "}\n"
        "```\n"
        "This is affecting our checkout flow for a subset of customers. Can "
        "someone check the DB pool health on your end?",
        "technical_bug", "high", False, "clear",
        "Intermittent server-side 500s with a request trace pointing to DB pool timeouts; needs backend engineering investigation.",
        {"product_area": "api", "previous_tickets_30d": 1, "has_attachments": False},
    ))
    tickets.append(mk(
        10, "2026-09-11T07:38:19Z", "email", "C-6335", "pro", "2024-01-15",
        "Webhook delivery returning 500 with malformed payload",
        "Our webhook receiver is logging 500s from our own side because the "
        "payload you're sending appears malformed. Here is what we captured:\n\n"
        "```json\n"
        "{\n"
        "  \"event\": \"order.updated\",\n"
        "  \"data\": {\n"
        "    \"order_id\": \"ord_5567\",\n"
        "    \"status\": null,\n"
        "  }\n"
        "}\n"
        "```\n"
        "Note the trailing comma before the closing brace - that's invalid "
        "JSON and our parser rejects it outright, hence our 500. Could you "
        "check your webhook serializer for this bug?",
        "technical_bug", "high", False, "clear",
        "Malformed JSON payload from webhook serializer is a concrete, evidenced bug in our system needing an engineering fix.",
        {"product_area": "webhooks", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        11, "2026-09-12T21:14:47Z", "chat", "C-6440", "free", "2025-06-10",
        "yaml config rejected after update",
        "hey so i updated my integration config and now it wont load, i get "
        "a validation error. this is my config file:\n\n"
        "```yaml\n"
        "integration:\n"
        "  name: acme-sync\n"
        "  retries: 3\n"
        "  endpoints:\n"
        "    - url: https://api.example.com/sync\n"
        "      method: POST\n"
        "  auth:\n"
        "    type: bearer\n"
        "  timeout: \"30s\n"
        "```\n"
        "not sure what's wrong with it, worked fine last week",
        "technical_bug", "medium", False, "clear",
        "Config parsing failure caused by an unterminated string in the YAML (missing closing quote on timeout); a concrete, fixable bug/config issue.",
        {"product_area": "data_export", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        12, "2026-09-13T15:29:58Z", "api", "C-6551", "enterprise", "2019-11-02",
        "Deployment config YAML causing pods to crash-loop",
        "After applying the new recommended config template, our workers "
        "enter a crash-loop. Relevant excerpt:\n\n"
        "```yaml\n"
        "worker:\n"
        "  concurrency: 8\n"
        "  queue: default\n"
        "  resources:\n"
        "    limits:\n"
        "      memory: 256Mi\n"
        "    requests:\n"
        "      memory: 512Mi\n"
        "```\n"
        "We suspect the requests > limits mismatch on memory is invalid and "
        "causing the scheduler to reject/kill the pods repeatedly. Can you "
        "confirm and update the docs/template if so?",
        "technical_bug", "high", False, "clear",
        "Config template itself contains an invalid resource spec (requests exceeding limits) causing crash-loops; a documented bug to fix at the source.",
        {"product_area": "api", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        13, "2026-09-14T04:51:26Z", "web_form", "C-6667", "pro", "2023-08-08",
        "Dashboard latency degrading badly over the past week",
        "Our dashboard has gotten progressively slower over the last 7 days. "
        "Page loads that used to take ~1s now take 8-12s. We pulled some "
        "timing logs from our monitoring:\n\n"
        "```\n"
        "2026-09-08 10:00:01 dashboard_load_ms=1120\n"
        "2026-09-09 10:00:03 dashboard_load_ms=2430\n"
        "2026-09-10 10:00:02 dashboard_load_ms=4110\n"
        "2026-09-11 10:00:04 dashboard_load_ms=6870\n"
        "2026-09-12 10:00:01 dashboard_load_ms=9920\n"
        "2026-09-13 10:00:05 dashboard_load_ms=11840\n"
        "```\n"
        "This trend is really concerning and it's affecting our team's daily "
        "workflow. Nothing changed on our side that we're aware of. Can "
        "someone investigate what's degrading on the backend?",
        "technical_bug", "high", False, "clear",
        "Clear, quantified performance regression trend from the customer's own timing logs; needs backend performance investigation.",
        {"product_area": "dashboard", "previous_tickets_30d": 1, "has_attachments": False},
    ))
    tickets.append(mk(
        14, "2026-09-15T13:36:05Z", "email", "C-6778", "pro", "2022-12-19",
        "Data export totals don't match dashboard totals",
        "I exported our monthly usage report via the data export tool and "
        "the total row count is 4,812, but the dashboard summary widget "
        "shows 4,930 for the same date range and filters. This is a "
        "meaningful discrepancy (118 records) for our monthly reconciliation. "
        "Both were pulled today within a few minutes of each other using the "
        "identical date range (Aug 1 - Aug 31) and the same account filter. "
        "Can someone check why the export pipeline and dashboard aggregation "
        "are disagreeing?",
        "technical_bug", "medium", False, "clear",
        "Concrete data-mismatch report between two systems with matching filters/date ranges; a data-pipeline bug for engineering to reconcile.",
        {"product_area": "data_export", "previous_tickets_30d": 0, "has_attachments": False},
    ))

    # ---------------- ESCALATION (4) ----------------
    tickets.append(mk(
        15, "2026-09-16T09:00:00Z", "email", "C-7001", "pro", "2023-02-27",
        "Considering cancelling - this has been a rough month",
        "I'll be honest, we're seriously considering moving to a competitor. "
        "We've had three separate issues this month (sync failures, a billing "
        "error, and now slow support responses) and it's eroding our trust. "
        "Here's the ticket history export our team keeps for internal review:\n\n"
        "```json\n"
        "{\n"
        "  \"open_issues_this_month\": 3,\n"
        "  \"issues\": [\"sync_failure\", \"billing_error\", \"slow_response\"],\n"
        "  \"account_id\": \"C-7001\"\n"
        "}\n"
        "```\n"
        "I need someone to actually call me and walk through what's going on, "
        "or we're going to start migrating off the platform next week.",
        "escalation", "high", True, "clear",
        "Explicit churn threat with a concrete migration deadline from a paying customer; requires human account-management outreach.",
        {"product_area": "unknown", "previous_tickets_30d": 3, "has_attachments": False},
    ))
    tickets.append(mk(
        16, "2026-09-17T06:12:40Z", "api", "C-7112", "enterprise", "2018-04-05",
        "SLA breach - uptime commitment violated this quarter",
        "Per our contract, you committed to 99.95% uptime. Our internal "
        "monitoring shows actual uptime of 99.61% this quarter, which is a "
        "clear breach of the SLA in section 4.2 of our agreement. We expect "
        "a formal response with root cause, remediation plan, and applicable "
        "service credits within 5 business days, or we will escalate this to "
        "our legal team.",
        "escalation", "critical", True, "clear",
        "Formal contractual SLA breach claim from an enterprise customer with a legal escalation threat; requires immediate human account/legal involvement.",
        {"product_area": "unknown", "previous_tickets_30d": 1, "has_attachments": False},
    ))
    tickets.append(mk(
        17, "2026-09-18T17:44:12Z", "email", "C-7223", "enterprise", "2017-10-11",
        "Re: Re: Re: Unacceptable - need a call TODAY",
        "I am extremely frustrated. This is the third email in this thread "
        "and I still have no answer. My team has been blocked for two days "
        "and nobody from your side has picked up the phone. I am the VP of "
        "Engineering here and I will be raising this with your CEO directly "
        "if I don't get a call within the hour. This is not how a partner "
        "at our contract level should be treated. Please have someone senior "
        "call me immediately.",
        "escalation", "critical", True, "clear",
        "Executive-level escalation thread with an explicit threat to go over support's head and demand for immediate senior contact; requires human handling now.",
        {"product_area": "unknown", "previous_tickets_30d": 2, "has_attachments": False},
    ))
    tickets.append(mk(
        18, "2026-09-19T22:08:55Z", "chat", "C-7334", "enterprise", "2021-01-09",
        "Still down - deadline was yesterday, need status now",
        "You told us this outage would be resolved by end of day yesterday. "
        "It is still down. Our monitoring shows the failure pattern still "
        "recurring:\n\n"
        "```\n"
        "2026-09-19 21:00:01 status=degraded errors=42\n"
        "2026-09-19 21:30:02 status=degraded errors=51\n"
        "2026-09-19 22:00:03 status=degraded errors=58\n"
        "```\n"
        "Our internal deadline to report to our own "
        "customers has now passed and we look bad because of this. I need a "
        "real update from someone with actual authority on this, not another "
        "'we're looking into it' message. This needs to be treated as a "
        "top priority right now.",
        "escalation", "critical", True, "clear",
        "Missed-deadline outage follow-up with explicit demand for a senior contact and top-priority handling; requires human escalation immediately.",
        {"product_area": "unknown", "previous_tickets_30d": 4, "has_attachments": False},
    ))

    # ---------------- FAQ (6) ----------------
    tickets.append(mk(
        19, "2026-09-20T10:10:10Z", "chat", "C-8001", "free", "2025-07-01",
        "How do I add a teammate to my workspace?",
        "hi! new to the platform, could someone tell me the steps to invite "
        "a coworker to your workspace? i looked in settings but couldn't find it.\n"
        "thanks in advance!",
        "faq", "low", False, "clear",
        "Simple how-to question about inviting teammates; answerable with existing documentation, no urgency.",
        {"product_area": "dashboard", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        20, "2026-09-21T14:26:37Z", "web_form", "C-8112", "pro", "2024-02-14",
        "How to set up custom fields in reports?",
        "I want to add a custom field to my weekly report template so I can "
        "track a metric specific to our business. Is that possible, and if "
        "so where do I configure it? A short walkthrough would be great, "
        "no rush on this one.",
        "faq", "low", False, "clear",
        "Standard how-to question about report customization; documentation-answerable, no urgency.",
        {"product_area": "dashboard", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        21, "2026-09-22T08:03:21Z", "email", "C-8223", "pro", "2023-09-30",
        "Does the Slack integration support threaded replies?",
        "Before we roll this out to our whole team, I want to confirm: does "
        "the Slack integration post threaded replies for follow-up comments, "
        "or does every comment show up as a brand new top-level message in "
        "the channel? Here's the sample payload our test webhook received:\n\n"
        "```json\n"
        "{\n"
        "  \"event\": \"comment.created\",\n"
        "  \"thread_ts\": null,\n"
        "  \"channel\": \"#support-test\"\n"
        "}\n"
        "```\n"
        "The thread_ts being null makes me think it's not threading, but "
        "wanted to confirm before we set expectations with our team.",
        "faq", "low", False, "clear",
        "Pre-sales/usage question about third-party Slack integration behavior; informational, no issue to fix.",
        {"product_area": "webhooks", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        22, "2026-09-23T19:51:02Z", "api", "C-8334", "free", "2025-05-05",
        "What's my current API rate limit and how do I check usage?",
        "I keep hitting 429s and I'm not sure what my current rate limit "
        "actually is or where to view my usage against it. Here is the "
        "rate-limit config section I found in our own integration file, "
        "just to confirm I'm reading it right:\n\n"
        "```yaml\n"
        "rate_limit:\n"
        "  plan: free\n"
        "  requests_per_minute: 60\n"
        "  burst: 10\n"
        "```\n"
        "Is there an endpoint or dashboard page that shows live usage "
        "against this? Just want to plan our request volume better going "
        "forward.",
        "faq", "medium", False, "clear",
        "Question about understanding rate limits/quota and where to view usage; informational request, not a live outage.",
        {"product_area": "api", "previous_tickets_30d": 1, "has_attachments": False},
    ))
    tickets.append(mk(
        23, "2026-09-24T02:47:59Z", "web_form", "C-8445", "free", "2025-08-19",
        "Locked out of my account, need to reset access",
        "I can't log in anymore, it says my account is locked after too many "
        "attempts. I know my password is correct, or at least I think so. "
        "Can you unlock it or send me a reset link? My email on file is "
        "j.martinez@example.com.",
        "faq", "medium", False, "clear",
        "Routine account-access/lockout reset request; standard self-service or quick support fix, not a bug.",
        {"product_area": "auth", "previous_tickets_30d": 0, "has_attachments": False},
    ))
    tickets.append(mk(
        24, "2026-09-25T16:16:16Z", "chat", "C-8556", "pro", "2024-06-06",
        "it doesnt work",
        "it doesnt work",
        "faq", "low", True, "insufficient_info",
        "Body and subject give no actionable detail about what feature, error, or context is involved; cannot determine route confidently, so a human must follow up to gather more information before triage.",
        {"product_area": "unknown", "previous_tickets_30d": 0, "has_attachments": False},
    ))

    # Insert the two remaining special-case requirements by REPLACING two
    # existing faq-clear-cut slots would break composition counts, so instead
    # we embed the two required ambiguous cross-category cases by adjusting
    # two of the tickets above (billing+bug double-charge -> ticket 3 already
    # covers double charge but is clearly billing; the schema wants a genuinely
    # ambiguous cross-category one). We handle this by overwriting ticket 3
    # and ticket 16 with ambiguous cross-category variants below.

    # Overwrite #3: billing+technical_bug ambiguous double-charge (system glitch or billing glitch?)
    tickets[2] = mk(
        3, "2026-09-04T18:03:44Z", "email", "C-3311", "enterprise", "2022-06-01",
        "Double charge on enterprise invoice #INV-88213 - maybe a sync bug?",
        "Our finance team flagged that invoice INV-88213 for $4,800 was "
        "charged twice to our corporate card on the same day (Sept 1st). "
        "Here is the export from our banking portal:\n\n"
        "```csv\n"
        "date,description,amount\n"
        "2026-09-01,ACME SUPPORT SOFTWARE,4800.00\n"
        "2026-09-01,ACME SUPPORT SOFTWARE,4800.00\n"
        "2026-08-01,ACME SUPPORT SOFTWARE,4800.00\n"
        "```\n"
        "We also noticed our account dashboard shows two separate 'sync "
        "retry' events logged at the exact same timestamps as the charges, "
        "so we're not sure if this is a straightforward billing duplicate "
        "or if a backend retry bug fired the charge twice. Either way we "
        "need this refunded and understood before our Friday close.",
        "billing", "high", False, "ambiguous",
        "Duplicate charge could be a plain billing error or the symptom of a backend retry/sync bug given the matching 'sync retry' log timestamps; routed to billing as the primary customer-facing fix (refund) while flagging the possible technical root cause for follow-up.",
        {"product_area": "billing_portal", "previous_tickets_30d": 0, "has_attachments": True},
    )

    # Overwrite #16: escalation+technical_bug ambiguous SLA breach tied to ongoing outage
    tickets[15] = mk(
        16, "2026-09-17T06:12:40Z", "api", "C-7112", "enterprise", "2018-04-05",
        "SLA breach tied to ongoing outage - contract and technical issue",
        "Per our contract, you committed to 99.95% uptime. Our internal "
        "monitoring shows actual uptime of 99.61% this quarter, driven "
        "almost entirely by the unresolved intermittent outage on the "
        "/v2/orders endpoint that our engineers already reported (recurring "
        "500s, DB pool timeouts). This is both a contractual SLA breach and "
        "an unresolved technical bug - we need root cause AND a formal "
        "response on service credits within 5 business days, or we escalate "
        "to legal.",
        "escalation", "critical", True, "ambiguous",
        "Genuinely spans two categories: the underlying cause is an unresolved technical_bug (recurring 500s), but the customer's explicit framing is a contractual SLA/legal escalation demanding account-level response, so escalation is chosen as the primary route with the technical root cause noted for engineering follow-up.",
        {"product_area": "api", "previous_tickets_30d": 1, "has_attachments": False},
    )

    # Long-body requirement (>=2, >=1500 chars): extend ticket 13 (already long-ish) and add bulk to ticket 6.
    long_addendum_13 = (
        "\n\nAdditional context our on-call engineer put together while "
        "investigating before filing this: we checked our own application "
        "logs, network path (traceroute to your edge nodes shows nothing "
        "unusual), browser dev tools waterfall (the slowdown appears to be "
        "entirely server response time, not asset loading or client-side "
        "rendering), and we also tried from three different office networks "
        "and two different ISPs to rule out anything local to us. In every "
        "case the same gradual multi-day degradation pattern shows up, which "
        "is why we're confident this points to something on the backend "
        "rather than our environment. We also compared against a colleague's "
        "account on a completely separate workspace/org and their dashboard "
        "loads normally in under a second, which suggests this may be scoped "
        "to our specific account, workspace, or the dataset size we've "
        "accumulated over the past year (we do have significantly more "
        "historical records than most accounts our size, per an earlier "
        "conversation with your sales team when we onboarded). If it helps "
        "narrow things down, the degradation seems worse specifically on the "
        "'Trends' and 'Cohorts' widgets, while the simpler 'Overview' widget "
        "still loads quickly even now. We're happy to hop on a call and share "
        "screen recordings, HAR files, or anything else that would help your "
        "team pinpoint this faster, since it's now materially affecting how "
        "our team plans its day and we'd like to avoid this becoming a "
        "bigger issue as our data volume continues to grow month over month."
    )
    tickets[12]["body"] = tickets[12]["body"] + long_addendum_13

    long_addendum_6 = (
        "\n\nFor additional context: we've reviewed our payment method "
        "settings on our side multiple times and confirmed the card has a "
        "high available balance well above the renewal amount, a valid "
        "expiration date more than two years out, and no fraud holds or "
        "recent disputes associated with it according to our own bank's "
        "app and customer service line, whom we called directly to double "
        "check before filing this ticket. We also tried updating the card "
        "on file to a completely different card from a different bank as a "
        "test, and the very next automated retry still failed with the same "
        "decline code shown above, which strongly suggests the failure is "
        "not actually about the card itself but something in how the retry "
        "or renewal charge is being constructed or routed through the "
        "payment gateway on your end. Given that our account is on an "
        "enterprise contract with dozens of active seats relying on "
        "uninterrupted access, and the risk of suspension in 48 hours as "
        "noted, we would really appreciate this being looked at by someone "
        "on your payments engineering team rather than a generic billing "
        "macro response, since we've already ruled out every customer-side "
        "cause we can think of and this is now blocking our whole team from "
        "planning around a very real business continuity risk this week."
    )
    tickets[5]["body"] = tickets[5]["body"] + long_addendum_6

    # One-line body requirement (2 total): ticket 2 and ticket 24 already
    # qualify (single short line bodies). Confirm ticket 2's body is one line
    # (it is, no \n). Good.

    # Fake-credential-in-log requirement: embed synthetic fake creds in ticket 9's log.
    tickets[8]["body"] = tickets[8]["body"].replace(
        "\"trace\": \"OrdersService.fetch -> DBPool.acquire -> timeout after 3000ms\"\n"
        "}\n"
        "```",
        "\"trace\": \"OrdersService.fetch -> DBPool.acquire -> timeout after 3000ms\",\n"
        "  \"debug_context\": {\n"
        "    \"api_key\": \"sk-synth-abc123\",\n"
        "    \"password\": \"hunter2-synth\"\n"
        "  }\n"
        "}\n"
        "```\n"
        "(We noticed our debug logging accidentally includes what look like "
        "credential fields above - these are clearly placeholder/test values "
        "from our staging environment, not real secrets, but flagging in "
        "case your redaction tooling should be scrubbing this field regardless.)"
    )
    tickets[8]["expected"]["rationale"] += (
        " Note: body contains an embedded fake/synthetic credential pair "
        "(api_key/password) intended to exercise the router's redaction step; "
        "values are clearly non-production placeholders."
    )

    return tickets


def _check_type(value, expected_type):
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    return False


def validate_ticket(t, idx):
    errors = []

    required_top = ["ticket_id", "created_at", "channel", "customer", "subject", "body", "expected"]
    for f in required_top:
        if f not in t:
            errors.append("record %d: missing required field '%s'" % (idx, f))
    allowed_top = set(required_top + ["metadata"])
    for k in t.keys():
        if k not in allowed_top:
            errors.append("record %d: unexpected top-level field '%s'" % (idx, k))

    if "ticket_id" in t:
        if not isinstance(t["ticket_id"], str) or not TICKET_ID_RE.match(t["ticket_id"]):
            errors.append("record %d: bad ticket_id '%s'" % (idx, t.get("ticket_id")))
        else:
            expected_id = "TCK-%04d" % idx
            if t["ticket_id"] != expected_id:
                errors.append("record %d: ticket_id out of sequence, expected %s got %s" % (idx, expected_id, t["ticket_id"]))

    if "created_at" in t:
        if not isinstance(t["created_at"], str) or not DATETIME_RE.match(t["created_at"]):
            errors.append("record %d: bad created_at '%s'" % (idx, t.get("created_at")))

    if "channel" in t and t["channel"] not in CHANNEL_ENUM:
        errors.append("record %d: bad channel '%s'" % (idx, t.get("channel")))

    if "customer" in t:
        cust = t["customer"]
        if not isinstance(cust, dict):
            errors.append("record %d: customer not an object" % idx)
        else:
            for f in ["id", "tier", "since"]:
                if f not in cust:
                    errors.append("record %d: customer missing '%s'" % (idx, f))
            for k in cust.keys():
                if k not in ("id", "tier", "since"):
                    errors.append("record %d: customer has unexpected field '%s'" % (idx, k))
            if "id" in cust and (not isinstance(cust["id"], str) or not CUSTOMER_ID_RE.match(cust["id"])):
                errors.append("record %d: bad customer.id '%s'" % (idx, cust.get("id")))
            if "tier" in cust and cust["tier"] not in TIER_ENUM:
                errors.append("record %d: bad customer.tier '%s'" % (idx, cust.get("tier")))
            if "since" in cust and (not isinstance(cust["since"], str) or not DATE_RE.match(cust["since"])):
                errors.append("record %d: bad customer.since '%s'" % (idx, cust.get("since")))

    if "subject" in t:
        s = t["subject"]
        if not isinstance(s, str) or not (3 <= len(s) <= 200):
            errors.append("record %d: subject length invalid (%d chars)" % (idx, len(s) if isinstance(s, str) else -1))

    if "body" in t:
        b = t["body"]
        if not isinstance(b, str) or len(b) < 5:
            errors.append("record %d: body too short" % idx)

    if "metadata" in t:
        md = t["metadata"]
        if not isinstance(md, dict):
            errors.append("record %d: metadata not an object" % idx)
        else:
            for k in md.keys():
                if k not in ("product_area", "previous_tickets_30d", "has_attachments"):
                    errors.append("record %d: metadata has unexpected field '%s'" % (idx, k))
            if "product_area" in md and md["product_area"] not in PRODUCT_AREA_ENUM:
                errors.append("record %d: bad metadata.product_area '%s'" % (idx, md.get("product_area")))
            if "previous_tickets_30d" in md and not (_check_type(md["previous_tickets_30d"], "integer") and md["previous_tickets_30d"] >= 0):
                errors.append("record %d: bad metadata.previous_tickets_30d '%s'" % (idx, md.get("previous_tickets_30d")))
            if "has_attachments" in md and not _check_type(md["has_attachments"], "boolean"):
                errors.append("record %d: bad metadata.has_attachments '%s'" % (idx, md.get("has_attachments")))

    if "expected" in t:
        exp = t["expected"]
        if not isinstance(exp, dict):
            errors.append("record %d: expected not an object" % idx)
        else:
            required_exp = ["route", "priority", "requires_human", "ambiguity", "rationale"]
            for f in required_exp:
                if f not in exp:
                    errors.append("record %d: expected missing '%s'" % (idx, f))
            for k in exp.keys():
                if k not in required_exp:
                    errors.append("record %d: expected has unexpected field '%s'" % (idx, k))
            if "route" in exp and exp["route"] not in ROUTE_ENUM:
                errors.append("record %d: bad expected.route '%s'" % (idx, exp.get("route")))
            if "priority" in exp and exp["priority"] not in PRIORITY_ENUM:
                errors.append("record %d: bad expected.priority '%s'" % (idx, exp.get("priority")))
            if "requires_human" in exp and not _check_type(exp["requires_human"], "boolean"):
                errors.append("record %d: bad expected.requires_human '%s'" % (idx, exp.get("requires_human")))
            if "ambiguity" in exp and exp["ambiguity"] not in AMBIGUITY_ENUM:
                errors.append("record %d: bad expected.ambiguity '%s'" % (idx, exp.get("ambiguity")))
            if "rationale" in exp and (not isinstance(exp["rationale"], str) or len(exp["rationale"]) < 20):
                errors.append("record %d: rationale too short" % idx)

    return errors


def self_validate(tickets):
    all_errors = []
    for i, t in enumerate(tickets, start=1):
        all_errors.extend(validate_ticket(t, i))

    if len(tickets) != 24:
        all_errors.append("expected 24 tickets, got %d" % len(tickets))

    ids = [t["ticket_id"] for t in tickets]
    expected_ids = ["TCK-%04d" % i for i in range(1, 25)]
    if ids != expected_ids:
        all_errors.append("ticket_id sequence mismatch: %r" % (ids,))

    route_counts = {}
    for t in tickets:
        r = t["expected"]["route"]
        route_counts[r] = route_counts.get(r, 0) + 1
    expected_counts = {"billing": 6, "technical_bug": 8, "escalation": 4, "faq": 6}
    if route_counts != expected_counts:
        all_errors.append("route counts mismatch: got %r expected %r" % (route_counts, expected_counts))

    json_blocks = sum(1 for t in tickets if "```json" in t["body"])
    yaml_blocks = sum(1 for t in tickets if "```yaml" in t["body"])
    stack_or_log = sum(
        1 for t in tickets
        if ("Traceback" in t["body"] or "FATAL EXCEPTION" in t["body"] or "trace" in t["body"].lower()
            or re.search(r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\b", t["body"]))
    )
    csv_blocks = sum(1 for t in tickets if "```csv" in t["body"])
    one_liners = sum(1 for t in tickets if "\n" not in t["body"] and len(t["body"]) < 200)
    long_bodies = sum(1 for t in tickets if len(t["body"]) >= 1500)

    fmt_coverage = {
        "json_blocks (>=6)": json_blocks,
        "yaml_blocks (>=3)": yaml_blocks,
        "stack_or_log (>=5)": stack_or_log,
        "csv_blocks (>=1)": csv_blocks,
        "one_liners (==2)": one_liners,
        "long_bodies (>=2, >=1500 chars)": long_bodies,
    }
    if json_blocks < 6:
        all_errors.append("json_blocks coverage insufficient: %d < 6" % json_blocks)
    if yaml_blocks < 3:
        all_errors.append("yaml_blocks coverage insufficient: %d < 3" % yaml_blocks)
    if stack_or_log < 5:
        all_errors.append("stack_or_log coverage insufficient: %d < 5" % stack_or_log)
    if csv_blocks < 1:
        all_errors.append("csv_blocks coverage insufficient: %d < 1" % csv_blocks)
    if one_liners != 2:
        all_errors.append("one_liner count mismatch: %d != 2" % one_liners)
    if long_bodies < 2:
        all_errors.append("long_bodies coverage insufficient: %d < 2" % long_bodies)

    fake_cred_tickets = [t["ticket_id"] for t in tickets if "sk-synth-" in t["body"] or "hunter2-synth" in t["body"]]
    if len(fake_cred_tickets) < 1:
        all_errors.append("no ticket contains the required fake-credential edge case")

    insufficient_info = [t["ticket_id"] for t in tickets if t["expected"]["ambiguity"] == "insufficient_info"]
    if len(insufficient_info) != 1:
        all_errors.append("expected exactly 1 insufficient_info ticket, got %d (%r)" % (len(insufficient_info), insufficient_info))

    ambiguous = [t["ticket_id"] for t in tickets if t["expected"]["ambiguity"] == "ambiguous"]
    if len(ambiguous) != 2:
        all_errors.append("expected exactly 2 ambiguous tickets, got %d (%r)" % (len(ambiguous), ambiguous))

    escalations = [t for t in tickets if t["expected"]["route"] == "escalation"]
    if len(escalations) != 4 or not all(t["expected"]["requires_human"] for t in escalations):
        all_errors.append("not all 4 escalations have requires_human=True")

    requires_human_count = sum(1 for t in tickets if t["expected"]["requires_human"])
    # 4 escalations + payment-failure (TCK-0006) + vague ticket (TCK-0024) = at least 6
    required_human_ids = {"TCK-0015", "TCK-0016", "TCK-0017", "TCK-0018", "TCK-0006", "TCK-0024"}
    actual_human_ids = {t["ticket_id"] for t in tickets if t["expected"]["requires_human"]}
    if not required_human_ids.issubset(actual_human_ids):
        all_errors.append("missing required requires_human=True on: %r" % (required_human_ids - actual_human_ids))

    summary = {
        "total": len(tickets),
        "route_counts": route_counts,
        "format_coverage": fmt_coverage,
        "fake_credential_tickets": fake_cred_tickets,
        "insufficient_info_tickets": insufficient_info,
        "ambiguous_tickets": ambiguous,
        "requires_human_count": requires_human_count,
    }
    return all_errors, summary


def main():
    tickets = build_tickets()
    # RNG retained/used for reproducibility of any future randomized fields;
    # currently the dataset content is fully deterministic/hand-authored to
    # exactly satisfy the specified composition, so RNG has no active draws
    # in this version but is seeded for future extension.
    RNG.random()

    errors, summary = self_validate(tickets)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        for t in tickets:
            line = json.dumps(t, ensure_ascii=False, sort_keys=False)
            f.write(line + "\n")

    # Re-read and re-validate with json.loads exactly as required.
    reread_errors = []
    with open(OUT_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) != 24:
        reread_errors.append("file does not contain exactly 24 lines: %d" % len(lines))
    parsed = []
    for i, line in enumerate(lines, start=1):
        try:
            obj = json.loads(line)
            parsed.append(obj)
        except Exception as e:
            reread_errors.append("line %d failed to parse: %s" % (i, e))

    print("=== Synthetic Support Ticket Generator ===")
    print("Output file: %s" % OUT_PATH)
    print("Total records: %d" % summary["total"])
    print("Route counts: %s" % json.dumps(summary["route_counts"]))
    print("Format coverage: %s" % json.dumps(summary["format_coverage"]))
    print("Fake-credential edge case tickets: %s" % summary["fake_credential_tickets"])
    print("Insufficient-info tickets: %s" % summary["insufficient_info_tickets"])
    print("Ambiguous (cross-category) tickets: %s" % summary["ambiguous_tickets"])
    print("requires_human=True count: %d" % summary["requires_human_count"])

    all_errors = errors + reread_errors
    if all_errors:
        print("\nVALIDATION FAILED (%d errors):" % len(all_errors))
        for e in all_errors:
            print(" - %s" % e)
        sys.exit(1)
    else:
        print("\nSelf-validation: PASSED (all %d records parsed, schema-conformant, sequential ids, composition/coverage requirements met)" % len(parsed))


if __name__ == "__main__":
    main()
