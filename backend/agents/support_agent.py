"""
Customer support agent implemented directly against the Mistral API.

Uses the mistralai SDK's native function/tool calling loop instead of
LangChain's AgentExecutor, which has a tool_call_id bug in v0.1.8.

Flow per ticket:
  1. query_customer_history
  2. classify_ticket
  3. draft_response
  4. send_auto_reply
  5. escalate_to_slack   (only if urgency = high | critical)
  6. mark_resolved
"""
import json
import logging
from typing import Any

from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage, ToolCall
from sqlalchemy.orm import Session

from config import get_settings
from agents.tools import make_tools

logger = logging.getLogger(__name__)
settings = get_settings()


SYSTEM_MESSAGE = """You are an expert customer support AI agent for a home services company.
Process each ticket by calling the provided tools in this exact order — never skip a step:

1. query_customer_history  – check for repeat issues using the customer email
2. classify_ticket         – assign urgency (critical/high/medium/low), category, summary, reasoning
3. draft_response          – write a warm, professional reply to the customer by name
4. send_auto_reply         – deliver the reply by email
5. escalate_to_slack       – ONLY if urgency is "high" or "critical"
6. mark_resolved           – close the ticket with a brief resolution note

Rules:
- Always address the customer by their first name.
- Be empathetic, concise, and professional.
- If a notification tool (email/Slack) fails, note it and continue with the remaining steps.
- Call mark_resolved as the final step regardless of earlier failures."""


# ── Tool schemas (Mistral function-calling format) ──────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_customer_history",
            "description": "Look up previous tickets from this customer to provide context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_email": {
                        "type": "string",
                        "description": "The customer's email address.",
                    }
                },
                "required": ["customer_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_ticket",
            "description": "Classify the support ticket by urgency and category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urgency": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Urgency level of the ticket.",
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "billing", "technical", "service_quality",
                            "scheduling", "cancellation", "feedback", "other",
                        ],
                        "description": "Category of the issue.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "One-sentence summary of the issue.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Brief explanation of the assigned urgency and category.",
                    },
                },
                "required": ["urgency", "category", "summary", "reasoning"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_response",
            "description": "Store the AI-drafted response to be sent to the customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "response_text": {
                        "type": "string",
                        "description": "Full reply text addressed to the customer.",
                    }
                },
                "required": ["response_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_auto_reply",
            "description": "Send an automatic email reply to the customer.",
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
            "description": "Send an escalation alert to the Slack support channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "urgency": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "summary": {"type": "string"},
                    "ticket_url": {"type": "string"},
                },
                "required": ["reason", "urgency", "customer_name", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_resolved",
            "description": "Mark the ticket as resolved after all actions are complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resolution_note": {
                        "type": "string",
                        "description": "Brief note on how the ticket was resolved.",
                    }
                },
                "required": ["resolution_note"],
            },
        },
    },
]


# ── Agent loop ───────────────────────────────────────────────────────────────

def process_ticket(ticket_data: dict[str, Any], db: Session) -> dict[str, Any]:
    """
    Run the Mistral tool-calling loop on a single ticket.
    Returns a result dict with success flag and summary.
    """
    ticket_id = str(ticket_data["id"])

    # Build a name → callable mapping from LangChain tools (for side-effects/DB writes)
    lc_tools = make_tools(db, ticket_id)
    tool_map = {t.name: t for t in lc_tools}

    client = MistralClient(api_key=settings.mistral_api_key)

    messages = [
        ChatMessage(role="system", content=SYSTEM_MESSAGE),
        ChatMessage(
            role="user",
            content=(
                f"Process this support ticket.\n\n"
                f"Customer: {ticket_data['customer_name']} <{ticket_data['customer_email']}>\n"
                f"Subject: {ticket_data['subject']}\n"
                f"Message: {ticket_data['message']}\n"
                f"Ticket ID: {ticket_id}"
            ),
        ),
    ]

    final_answer = ""
    max_iterations = 15

    for iteration in range(max_iterations):
        logger.info("[ticket=%s] Agent iteration %d", ticket_id, iteration + 1)

        response = client.chat(
            model=settings.mistral_model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        assistant_msg = response.choices[0].message
        messages.append(assistant_msg)

        # If no tool calls → model is done
        if not assistant_msg.tool_calls:
            final_answer = assistant_msg.content or "Agent completed all steps."
            logger.info("[ticket=%s] Agent finished: %s", ticket_id, final_answer)
            break

        # Execute each tool call and append results
        for tc in assistant_msg.tool_calls:
            tool_name = tc.function.name
            try:
                raw_args = tc.function.arguments
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError as e:
                args = {}
                logger.warning("[ticket=%s] Bad JSON args for %s: %s", ticket_id, tool_name, e)

            logger.info("[ticket=%s] Calling tool: %s(%s)", ticket_id, tool_name, args)

            if tool_name in tool_map:
                try:
                    result = tool_map[tool_name].invoke(args)
                    result_str = result if isinstance(result, str) else json.dumps(result)
                except Exception as exc:
                    result_str = f"Tool error: {exc}"
                    logger.error("[ticket=%s] Tool %s failed: %s", ticket_id, tool_name, exc)
            else:
                result_str = f"Unknown tool: {tool_name}"
                logger.warning("[ticket=%s] Unknown tool: %s", ticket_id, tool_name)

            logger.info("[ticket=%s] Tool result: %s", ticket_id, result_str[:200])

            messages.append(ChatMessage(
                role="tool",
                content=result_str,
                name=tool_name,
                tool_call_id=tc.id,
            ))
    else:
        logger.warning("[ticket=%s] Reached max iterations (%d)", ticket_id, max_iterations)
        final_answer = "Agent reached max iterations."

    return {
        "ticket_id": ticket_id,
        "success": True,
        "summary": final_answer,
        "steps": iteration + 1,
    }
