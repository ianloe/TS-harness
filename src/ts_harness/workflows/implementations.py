"""Node implementations for the four draft-only initial workflows."""

from __future__ import annotations

from typing import Any

from ts_harness.agents.roles import (
    ExecutionReport,
    PlannerAgent,
    PlanStep,
    VerifierAgent,
)
from ts_harness.approvals.queue import ApprovalQueue
from ts_harness.connectors.interfaces import (
    CalendarConnector,
    DriveConnector,
    MailConnector,
    WebResearchConnector,
)
from ts_harness.core.models import DataClass, RiskTier, Task
from ts_harness.core.store import StateStore
from ts_harness.finops.budget import BudgetManager
from ts_harness.gateway.gateway import ExecutionContext, ToolGateway, ToolSpec
from ts_harness.graph.engine import NodeHandler, NodeOutcome
from ts_harness.guardrails.injection import detect_injection_signals, quarantine_untrusted


def build_inbox_triage_handlers(
    *,
    mail: MailConnector,
    gateway: ToolGateway,
    planner: PlannerAgent,
    verifier: VerifierAgent,
) -> dict[str, NodeHandler]:
    """Build handlers for inbox_triage (classify, summarise, draft replies, propose labels)."""
    gateway.register(
        ToolSpec(
            name="read_inbox_messages",
            description="Read unread inbox messages",
            risk_tier=RiskTier.T0,
            connector_name="mail",
            handler=lambda args, ctx: [
                m.model_dump(mode="json")
                for m in mail.list_messages(limit=int(args.get("limit", 10)))
            ],
        )
    )
    gateway.register(
        ToolSpec(
            name="draft_email_reply",
            description="Create a draft reply (never sends)",
            risk_tier=RiskTier.T1,
            connector_name="mail",
            handler=lambda args, ctx: mail.create_draft(
                in_reply_to=str(args["in_reply_to"]),
                recipient=str(args["recipient"]),
                subject=str(args["subject"]),
                body=str(args["body"]),
            ).model_dump(mode="json"),
        )
    )
    gateway.register(
        ToolSpec(
            name="label_propose_message",
            description="Propose a label for an email",
            risk_tier=RiskTier.T1,
            connector_name="mail",
            handler=lambda args, ctx: mail.propose_label(
                message_id=str(args["message_id"]),
                label=str(args["label"]),
            ),
        )
    )

    def plan_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        plan = planner.plan(
            task.description or "Triage inbox messages",
            proposed_steps=[PlanStep(tool_name="read_inbox_messages", args={"limit": 10})],
            task_id=task.id,
            workflow_name=task.workflow_name,
        )
        return NodeOutcome(
            state_updates={"plan": plan.model_dump()},
            cost_incurred=plan.cost_amount,
        )

    def act_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        ctx = ExecutionContext(
            task_id=task.id,
            workflow_name=task.workflow_name,
            actor="executor",
            data_class=DataClass.PERSONAL,
            trust_level="user",
        )
        msgs_res = gateway.execute("read_inbox_messages", {"limit": 10}, ctx)
        messages: list[dict[str, Any]] = msgs_res.output
        summaries: list[dict[str, Any]] = []
        drafts: list[dict[str, Any]] = []
        labels: list[dict[str, Any]] = []

        for msg in messages:
            quarantined_body = quarantine_untrusted(str(msg["body"]), f"mail:{msg['id']}")
            scan = detect_injection_signals(str(msg["body"]))
            label = "quarantine-suspicious" if scan.suspicious else "needs-reply"
            lbl_res = gateway.execute(
                "label_propose_message",
                {"message_id": msg["id"], "label": label},
                ctx,
            )
            labels.append(lbl_res.output)

            if not scan.suspicious:
                draft_res = gateway.execute(
                    "draft_email_reply",
                    {
                        "in_reply_to": msg["id"],
                        "recipient": msg["sender"],
                        "subject": f"Re: {msg['subject']}",
                        "body": f"Thank you for your note regarding '{msg['subject']}'. "
                        f"I will review and follow up shortly.",
                    },
                    ctx,
                )
                drafts.append(draft_res.output)

            summaries.append(
                {
                    "id": msg["id"],
                    "sender": msg["sender"],
                    "subject": msg["subject"],
                    "suspicious": scan.suspicious,
                    "quarantined_excerpt": quarantined_body[:160],
                }
            )

        return NodeOutcome(
            state_updates={"summaries": summaries, "drafts": drafts, "labels": labels}
        )

    def verify_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        report = ExecutionReport(
            output_text=(
                f"Triaged {len(state.get('summaries', []))} messages; "
                f"created {len(state.get('drafts', []))} drafts (draft-only, none sent)."
            )
        )
        ver = verifier.verify(
            task.description or "Triage inbox",
            report,
            task_id=task.id,
            workflow_name=task.workflow_name,
        )
        return NodeOutcome(
            state_updates={"verification": ver.model_dump(), "summary": report.output_text},
            cost_incurred=ver.cost_amount,
        )

    return {"plan": plan_fn, "act": act_fn, "verify": verify_fn}


def build_meeting_prep_handlers(
    *,
    calendar: CalendarConnector,
    drive: DriveConnector,
    gateway: ToolGateway,
    planner: PlannerAgent,
    verifier: VerifierAgent,
) -> dict[str, NodeHandler]:
    """Build handlers for meeting_prep (read calendar & related docs, produce one-page brief)."""
    gateway.register(
        ToolSpec(
            name="read_calendar_events",
            description="Read upcoming calendar events",
            risk_tier=RiskTier.T0,
            connector_name="calendar",
            handler=lambda args, ctx: [
                e.model_dump(mode="json")
                for e in calendar.list_events(limit=int(args.get("limit", 5)))
            ],
        )
    )
    gateway.register(
        ToolSpec(
            name="read_drive_docs",
            description="Search related Drive documents",
            risk_tier=RiskTier.T0,
            connector_name="drive",
            handler=lambda args, ctx: [
                d.model_dump(mode="json")
                for d in drive.search_documents(str(args.get("query", "")), limit=3)
            ],
        )
    )

    def plan_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        plan = planner.plan(
            task.description or "Prepare meeting brief",
            proposed_steps=[PlanStep(tool_name="read_calendar_events")],
            task_id=task.id,
            workflow_name=task.workflow_name,
        )
        return NodeOutcome(
            state_updates={"plan": plan.model_dump()},
            cost_incurred=plan.cost_amount,
        )

    def act_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        ctx = ExecutionContext(
            task_id=task.id,
            workflow_name=task.workflow_name,
            actor="executor",
            data_class=DataClass.INTERNAL,
            trust_level="user",
        )
        events = gateway.execute("read_calendar_events", {"limit": 5}, ctx).output
        briefs: list[dict[str, Any]] = []
        source_urls: list[str] = []
        for evt in events:
            docs = gateway.execute("read_drive_docs", {"query": evt["title"]}, ctx).output
            for doc in docs:
                source_urls.append(doc["url"])
            briefs.append(
                {
                    "meeting": evt["title"],
                    "attendees": evt["attendees"],
                    "related_docs": [d["title"] for d in docs],
                    "brief": f"Brief for {evt['title']}: review {len(docs)} related document(s).",
                }
            )
        return NodeOutcome(state_updates={"briefs": briefs, "source_urls": source_urls})

    def verify_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        briefs = state.get("briefs", [])
        urls = set(state.get("source_urls", []))
        text = "\n".join(b["brief"] for b in briefs)
        ver = verifier.verify(
            task.description or "Meeting prep",
            ExecutionReport(output_text=text, source_urls=urls),
            task_id=task.id,
            workflow_name=task.workflow_name,
        )
        return NodeOutcome(
            state_updates={"verification": ver.model_dump(), "brief_text": text},
            cost_incurred=ver.cost_amount,
        )

    return {"plan": plan_fn, "act": act_fn, "verify": verify_fn}


def build_research_digest_handlers(
    *,
    web: WebResearchConnector,
    gateway: ToolGateway,
    planner: PlannerAgent,
    verifier: VerifierAgent,
) -> dict[str, NodeHandler]:
    """Build handlers for research_digest (bounded web research with citations + verifier)."""
    gateway.register(
        ToolSpec(
            name="search_web_sources",
            description="Bounded web search",
            risk_tier=RiskTier.T0,
            connector_name="web",
            handler=lambda args, ctx: [
                h.model_dump(mode="json") for h in web.search(str(args.get("query", "")), limit=5)
            ],
        )
    )

    def plan_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        plan = planner.plan(
            task.description or "Research digest",
            proposed_steps=[PlanStep(tool_name="search_web_sources", args={"query": task.title})],
            task_id=task.id,
            workflow_name=task.workflow_name,
        )
        return NodeOutcome(
            state_updates={"plan": plan.model_dump(), "query": task.title},
            cost_incurred=plan.cost_amount,
        )

    def loop_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        ctx = ExecutionContext(
            task_id=task.id,
            workflow_name=task.workflow_name,
            actor="executor",
            data_class=DataClass.PUBLIC,
            trust_level="user",
        )
        hits = gateway.execute(
            "search_web_sources",
            {"query": state.get("query", task.title)},
            ctx,
        ).output
        citations = [h["url"] for h in hits]
        digest_lines = [f"- {h['title']}: {h['snippet']} ({h['url']})" for h in hits]
        return NodeOutcome(
            state_updates={
                "hits": hits,
                "citations": citations,
                "digest_text": "\n".join(digest_lines),
            },
            action_signature=f"search:{state.get('query', task.title)}",
            continue_loop=False,
        )

    def verify_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        report = ExecutionReport(
            output_text=state.get("digest_text", ""),
            source_urls=set(state.get("citations", [])),
        )
        ver = verifier.verify(
            task.description or "Research digest",
            report,
            task_id=task.id,
            workflow_name=task.workflow_name,
        )
        return NodeOutcome(
            state_updates={"verification": ver.model_dump()},
            cost_incurred=ver.cost_amount,
        )

    return {"plan": plan_fn, "research_loop": loop_fn, "verify": verify_fn}


def build_weekly_review_handlers(
    *,
    store: StateStore,
    budget_manager: BudgetManager,
    approval_queue: ApprovalQueue,
    planner: PlannerAgent,
    verifier: VerifierAgent,
) -> dict[str, NodeHandler]:
    """Build handlers for weekly_review (aggregate activity, spend, and open approvals)."""

    def plan_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        plan = planner.plan(
            task.description or "Weekly review",
            task_id=task.id,
            workflow_name=task.workflow_name,
        )
        return NodeOutcome(
            state_updates={"plan": plan.model_dump()},
            cost_incurred=plan.cost_amount,
        )

    def act_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        tasks = store.list_tasks(limit=100)
        spend = budget_manager.get_spend_summary()
        pending_approvals = approval_queue.list_pending()
        report_text = (
            f"Weekly Review: {len(tasks)} total tasks tracked; "
            f"{len(pending_approvals)} pending approval(s); "
            f"daily spend {spend.daily_spend:.4f} {spend.currency}, "
            f"monthly spend {spend.monthly_spend:.4f} {spend.currency}."
        )
        return NodeOutcome(
            state_updates={
                "task_count": len(tasks),
                "pending_approvals": len(pending_approvals),
                "spend": spend.model_dump(mode="json"),
                "report_text": report_text,
            }
        )

    def verify_fn(state: dict[str, Any], task: Task) -> NodeOutcome:
        ver = verifier.verify(
            task.description or "Weekly review",
            ExecutionReport(output_text=state.get("report_text", "")),
            task_id=task.id,
            workflow_name=task.workflow_name,
        )
        return NodeOutcome(
            state_updates={"verification": ver.model_dump()},
            cost_incurred=ver.cost_amount,
        )

    return {"plan": plan_fn, "act": act_fn, "verify": verify_fn}
