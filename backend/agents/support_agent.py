"""
Goal-based customer support agent using Mistral native tool calling.

The agent is NOT given a fixed step order. It is given a GOAL and decides
its own execution path based on customer profile, history, and context.

Key behaviors:
- New customer with simple issue → quick classify + reply + resolve
- VIP or high churn risk → priority escalation + compensation offer
- Slack failure → automatically falls back to email escalation
- Repeat patterns → notes it in decision_notes for the insight engine
- Always self-evaluates before closing (feedback loop)
"""
import json
import logging
from typing import Any

from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
from sqlalchemy.orm import Session

from config import get_settings
from agents.tools import make_tools

logger = logging.getLogger(__name__)
settings = get_settings()


SYSTEM_MESSAGE = """You are an autonomous customer support AI agent for a home services company.

YOUR GOAL: Resolve each ticket as effectively as possible given the customer context.
You decide HOW to achieve this goal — there is no fixed step order.

AVAILABLE TOOLS:
- get_customer_profile     → always call this first; gives you history, churn risk, VIP status
- assess_and_classify      → classify urgency/category; record your decision strategy
- draft_response           → write the customer reply; adapt tone to context
- send_auto_reply          → deliver reply by email
- escalate_to_slack        → alert the ops team on Slack
- escalate_via_email       → FALLBACK if Slack fails; alerts support manager by email
- self_evaluate_and_resolve → ALWAYS call last; score your own performance

DECISION RULES (use your judgment, these are guidelines not commands):
1. After get_customer_profile, REASON about the situation:
   - High churn risk or VIP? → escalate regardless of urgency, offer compensation
   - Repeat same issue (3rd time)? → higher urgency, stronger response, flag the pattern
   - New customer, simple issue? → quick resolve, no escalation needed
   - Critical urgency? → always escalate

2. If escalate_to_slack fails → call escalate_via_email as fallback immediately

3. Adapt your draft_response:
   - VIP → senior, empathetic, immediate action promised
   - High churn risk → compensation/discount offer in response
   - New customer → warm welcome tone
   - Repeat complaints → acknowledge the pattern explicitly

4. self_evaluate_and_resolve is MANDATORY as the last step.
   Score yourself honestly: did you actually resolve the issue?

THINK before each tool call. Use the context you've gathered to make intelligent decisions."""


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_customer_profile",
            "description": "Get full customer profile: history, churn risk, VIP status, recurring patterns. Call first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_email": {"type": "string"},
                },
                "required": ["customer_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assess_and_classify",
            "description": "Classify ticket and record agent decision strategy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urgency": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "category": {
                        "type": "string",
                        "enum": ["billing", "technical", "service_quality",
                                 "scheduling", "cancellation", "feedback", "other"],
                    },
                    "summary": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "churn_risk": {"type": "string", "enum": ["low", "medium", "high"]},
                    "is_vip": {"type": "boolean"},
                    "decision_notes": {"type": "string"},
                },
                "required": ["urgency", "category", "summary", "reasoning",
                             "churn_risk", "is_vip", "decision_notes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_response",
            "description": "Write and store a customer reply. Tone adapts to VIP/churn/new customer context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "response_text": {"type": "string"},
                },
                "required": ["response_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_auto_reply",
            "description": "Deliver reply via email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_email": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "response_text": {"type": "string"},
                },
                "required": ["customer_email", "customer_name", "response_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_slack",
            "description": "Alert ops team on Slack. Use for high/critical urgency, high churn risk, or VIP customers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "urgency": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "summary": {"type": "string"},
                    "is_vip": {"type": "boolean"},
                    "churn_risk": {"type": "string"},
                    "ticket_url": {"type": "string"},
                },
                "required": ["reason", "urgency", "customer_name", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_via_email",
            "description": "Fallback escalation via email when Slack fails.",
            "parameters": {
                "type": "object",
                "properties": {
                    "escalation_summary": {"type": "string"},
                    "urgency": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["escalation_summary", "urgency", "customer_name", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "self_evaluate_and_resolve",
            "description": "Close ticket and score own performance. Always call last.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resolution_summary": {"type": "string"},
                    "self_score": {"type": "integer", "minimum": 1, "maximum": 5},
                    "resolution_successful": {"type": "boolean"},
                    "improvement_notes": {"type": "string"},
                },
                "required": ["resolution_summary", "self_score",
                             "resolution_successful", "improvement_notes"],
            },
        },
    },
]


def process_ticket(ticket_data: dict[str, Any], db: Session) -> dict[str, Any]:
    ticket_id = str(ticket_data["id"])
    tool_map = {t.name: t for t in make_tools(db, ticket_id)}
    client = MistralClient(api_key=settings.mistral_api_key)

    messages = [
        ChatMessage(role="system", content=SYSTEM_MESSAGE),
        ChatMessage(
            role="user",
            content=(
                f"Ticket to process:\n\n"
                f"Customer: {ticket_data['customer_name']} <{ticket_data['customer_email']}>\n"
                f"Subject: {ticket_data['subject']}\n"
                f"Message: {ticket_data['message']}\n"
                f"Ticket ID: {ticket_id}\n\n"
                f"Analyze the customer context and decide the best resolution path."
            ),
        ),
    ]

    final_answer = ""
    steps_taken = []

    for iteration in range(20):
        logger.info("[ticket=%s] iteration %d", ticket_id, iteration + 1)

        response = client.chat(
            model=settings.mistral_model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        assistant_msg = response.choices[0].message
        messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            final_answer = assistant_msg.content or "Agent completed."
            break

        for tc in assistant_msg.tool_calls:
            tool_name = tc.function.name
            try:
                raw = tc.function.arguments
                args = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                args = {}

            logger.info("[ticket=%s] → %s(%s)", ticket_id, tool_name,
                        str(args)[:120])
            steps_taken.append(tool_name)

            if tool_name in tool_map:
                try:
                    result = tool_map[tool_name].invoke(args)
                    result_str = result if isinstance(result, str) else json.dumps(result)
                except Exception as exc:
                    result_str = f"Tool error: {exc}"
                    logger.error("[ticket=%s] %s failed: %s", ticket_id, tool_name, exc)
            else:
                result_str = f"Unknown tool: {tool_name}"

            logger.info("[ticket=%s] ← %s: %s", ticket_id, tool_name, result_str[:200])

            messages.append(ChatMessage(
                role="tool",
                content=result_str,
                name=tool_name,
                tool_call_id=tc.id,
            ))

    logger.info("[ticket=%s] done. Steps: %s", ticket_id, steps_taken)
    return {
        "ticket_id": ticket_id,
        "success": True,
        "summary": final_answer,
        "steps": steps_taken,
    }
