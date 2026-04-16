"""
AI Operations Brain — Monitoring Dashboard
Displays live ticket status, urgency distribution, action logs, and manual controls.
"""
import os
import time
from datetime import datetime

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(
    page_title="AI Operations Brain",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helpers ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=10)
def fetch_stats() -> dict:
    try:
        r = httpx.get(f"{BACKEND_URL}/tickets/stats", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


@st.cache_data(ttl=10)
def fetch_tickets(status: str = "", urgency: str = "", limit: int = 100) -> list[dict]:
    params = {"limit": limit}
    if status:
        params["status"] = status
    if urgency:
        params["urgency"] = urgency
    try:
        r = httpx.get(f"{BACKEND_URL}/tickets/", params=params, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


@st.cache_data(ttl=10)
def fetch_action_logs(limit: int = 200) -> list[dict]:
    try:
        r = httpx.get(f"{BACKEND_URL}/logs/actions", params={"limit": limit}, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def submit_ticket(payload: dict) -> dict:
    try:
        r = httpx.post(f"{BACKEND_URL}/tickets/", json=payload, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


URGENCY_COLOR = {
    "critical": "#FF4B4B",
    "high": "#FF8C00",
    "medium": "#FFD700",
    "low": "#00C853",
}

STATUS_ICON = {
    "pending": "⏳",
    "processing": "⚙️",
    "resolved": "✅",
    "escalated": "🚨",
    "failed": "❌",
}

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/artificial-intelligence.png", width=64)
    st.title("AI Ops Brain")
    st.caption("Customer Support Automation")
    st.divider()

    page = st.radio(
        "Navigate",
        ["📊 Dashboard", "🎫 Tickets", "📋 Action Logs", "➕ Submit Ticket"],
        label_visibility="collapsed",
    )

    st.divider()
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"Backend: `{BACKEND_URL}`")
    st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")

    try:
        q = httpx.get(f"{BACKEND_URL}/tickets/queue/depth", timeout=3).json()
        queued = q.get("queued", 0)
        if queued > 0:
            st.warning(f"⏳ {queued} ticket(s) in queue")
        else:
            st.success("✅ Queue empty")
    except Exception:
        pass

# ── Page: Dashboard ───────────────────────────────────────────────────────────

if page == "📊 Dashboard":
    st.title("📊 Operations Dashboard")

    stats = fetch_stats()
    tickets = fetch_tickets(limit=200)

    if not stats:
        st.warning("Cannot reach backend. Make sure the backend service is running.")
        st.stop()

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Total Tickets", stats.get("total", 0))
    col2.metric("Pending", stats.get("pending", 0), delta_color="inverse")
    col3.metric("Processing", stats.get("processing", 0))
    col4.metric("Resolved", stats.get("resolved", 0), delta_color="normal")
    col5.metric("Escalated", stats.get("escalated", 0), delta_color="inverse")
    col6.metric("🔴 Critical Open", stats.get("critical_open", 0), delta_color="inverse")

    st.divider()

    if tickets:
        df = pd.DataFrame(tickets)
        df["created_at"] = pd.to_datetime(df["created_at"])
        df["date"] = df["created_at"].dt.date

        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Tickets by Status")
            status_counts = df["status"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]
            fig_status = px.pie(
                status_counts, names="status", values="count",
                color_discrete_sequence=px.colors.qualitative.Set2,
                hole=0.4,
            )
            fig_status.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=280)
            st.plotly_chart(fig_status, use_container_width=True)

        with col_b:
            st.subheader("Tickets by Urgency")
            urg = df[df["urgency"].notna()]["urgency"].value_counts().reset_index()
            urg.columns = ["urgency", "count"]
            color_map = {k: v for k, v in URGENCY_COLOR.items()}
            fig_urg = px.bar(
                urg, x="urgency", y="count",
                color="urgency", color_discrete_map=color_map,
            )
            fig_urg.update_layout(showlegend=False, height=280, margin=dict(t=0, b=0))
            st.plotly_chart(fig_urg, use_container_width=True)

        st.subheader("Ticket Volume Over Time")
        daily = df.groupby("date").size().reset_index(name="count")
        fig_line = px.line(daily, x="date", y="count", markers=True)
        fig_line.update_layout(height=220, margin=dict(t=0, b=0))
        st.plotly_chart(fig_line, use_container_width=True)

        st.subheader("Category Breakdown")
        if "category" in df.columns:
            cat = df[df["category"].notna()]["category"].value_counts().reset_index()
            cat.columns = ["category", "count"]
            fig_cat = px.bar(cat, x="count", y="category", orientation="h",
                             color="count", color_continuous_scale="Blues")
            fig_cat.update_layout(height=260, margin=dict(t=0, b=0), showlegend=False)
            st.plotly_chart(fig_cat, use_container_width=True)
    else:
        st.info("No tickets yet. Submit a ticket to see the dashboard come alive.")

# ── Page: Tickets ─────────────────────────────────────────────────────────────

elif page == "🎫 Tickets":
    st.title("🎫 Ticket Explorer")

    col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
    with col_f1:
        status_filter = st.selectbox(
            "Filter by status",
            ["", "pending", "processing", "resolved", "escalated", "failed"],
        )
    with col_f2:
        urgency_filter = st.selectbox(
            "Filter by urgency",
            ["", "critical", "high", "medium", "low"],
        )
    with col_f3:
        limit = st.number_input("Max results", min_value=10, max_value=200, value=50, step=10)

    tickets = fetch_tickets(status=status_filter, urgency=urgency_filter, limit=limit)

    if not tickets:
        st.info("No tickets found with the selected filters.")
    else:
        for t in tickets:
            urgency = t.get("urgency") or "unclassified"
            status = t.get("status", "pending")
            icon = STATUS_ICON.get(status, "❓")
            color = URGENCY_COLOR.get(urgency, "#888888")

            with st.expander(
                f"{icon} [{urgency.upper()}] {t['subject']} — {t['customer_name']}",
                expanded=(urgency in ("critical", "high") and status != "resolved"),
            ):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Customer:** {t['customer_name']}")
                c1.write(f"**Email:** {t['customer_email']}")
                c2.write(f"**Status:** {status}")
                c2.write(f"**Category:** {t.get('category') or '—'}")
                c3.write(f"**Escalated:** {'Yes 🚨' if t.get('escalated') else 'No'}")
                c3.write(f"**Auto-replied:** {'Yes ✉️' if t.get('auto_replied') else 'No'}")

                st.write("**Original Message:**")
                st.info(t["message"])

                if t.get("ai_summary"):
                    st.write("**AI Summary:**")
                    st.success(t["ai_summary"])

                if t.get("ai_response"):
                    st.write("**AI Response Sent:**")
                    st.write(t["ai_response"])

                if t.get("ai_reasoning"):
                    st.markdown(
                        f"<div style='background:#1e1e2e;border-left:3px solid #555;"
                        f"padding:8px 12px;border-radius:4px;margin-top:4px'>"
                        f"<span style='font-size:12px;color:#aaa'>🧠 AI Reasoning: {t['ai_reasoning']}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                if t.get("actions"):
                    st.write("**Action Log:**")
                    for action in t["actions"]:
                        ts = action.get("created_at", "")[:19].replace("T", " ") if action.get("created_at") else ""
                        st.caption(
                            f"`{ts}` · **{action['action_type']}** · "
                            f"{'✅' if action['status'] == 'success' else '❌'} {action.get('detail', '')}"
                        )

# ── Page: Action Logs ─────────────────────────────────────────────────────────

elif page == "📋 Action Logs":
    st.title("📋 Action Logs")

    logs = fetch_action_logs(limit=200)
    if not logs:
        st.info("No action logs yet.")
    else:
        df = pd.DataFrame(logs)
        df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")

        col1, col2 = st.columns(2)
        with col1:
            type_filter = st.multiselect(
                "Action type",
                options=sorted(df["action_type"].unique().tolist()),
                default=[],
            )
        with col2:
            status_filter = st.multiselect(
                "Status",
                options=["success", "failed"],
                default=[],
            )

        filtered = df.copy()
        if type_filter:
            filtered = filtered[filtered["action_type"].isin(type_filter)]
        if status_filter:
            filtered = filtered[filtered["status"].isin(status_filter)]

        st.dataframe(
            filtered[["created_at", "ticket_id", "action_type", "status", "detail"]],
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Action Type Distribution")
        counts = filtered["action_type"].value_counts().reset_index()
        counts.columns = ["action_type", "count"]
        fig = px.bar(counts, x="action_type", y="count", color="action_type")
        fig.update_layout(showlegend=False, height=220)
        st.plotly_chart(fig, use_container_width=True)

# ── Page: Submit Ticket ───────────────────────────────────────────────────────

elif page == "➕ Submit Ticket":
    st.title("➕ Submit a Test Ticket")
    st.caption(
        "Simulates a customer submitting a support ticket via the API. "
        "The AI agent will process it in the background."
    )

    with st.form("ticket_form"):
        name = st.text_input("Customer Name", placeholder="Jane Doe")
        email = st.text_input("Customer Email", placeholder="jane@example.com")
        subject = st.text_input("Subject", placeholder="Service not delivered on time")
        message = st.text_area(
            "Message",
            placeholder="Hi, I booked a cleaning for yesterday at 10am and nobody showed up...",
            height=150,
        )

        st.caption("💡 Try a critical complaint to see escalation in action.")

        submitted = st.form_submit_button("🚀 Submit Ticket", type="primary")

    if submitted:
        if not all([name, email, subject, message]):
            st.error("All fields are required.")
        else:
            with st.spinner("Submitting to AI system..."):
                result = submit_ticket({
                    "customer_name": name,
                    "customer_email": email,
                    "subject": subject,
                    "message": message,
                    "source": "dashboard",
                })
            if result.get("success") is not False:
                st.success(f"✅ Ticket accepted! ID: `{result.get('ticket_id')}`")
                st.info(result.get("summary", "Processing in background."))
                st.caption("Switch to the Dashboard or Tickets tab to track progress.")
                st.cache_data.clear()
            else:
                st.error(f"Failed to submit: {result.get('error', 'Unknown error')}")

    st.divider()
    st.subheader("Example Scenarios")

    examples = [
        {
            "label": "🔴 Critical — Service Not Delivered",
            "data": {
                "customer_name": "Sarah Al-Hassan",
                "customer_email": "sarah@example.com",
                "subject": "Cleaning team never arrived — 3rd time this happens",
                "message": (
                    "This is absolutely unacceptable. I booked a deep cleaning for today at 9am. "
                    "Nobody showed up. This is the THIRD time this has happened. "
                    "I am demanding a full refund and I will be contacting consumer protection if this is not resolved today."
                ),
            },
        },
        {
            "label": "🟠 High — Billing Dispute",
            "data": {
                "customer_name": "Omar Khalil",
                "customer_email": "omar.k@example.com",
                "subject": "Charged twice for same booking",
                "message": (
                    "Hi, I was charged twice for my booking on April 14th. "
                    "Please check transaction IDs 8821 and 8835. "
                    "I need an urgent refund for the duplicate charge."
                ),
            },
        },
        {
            "label": "🟡 Medium — Quality Complaint",
            "data": {
                "customer_name": "Lina Mansour",
                "customer_email": "lina.m@example.com",
                "subject": "Cleaning quality was poor",
                "message": (
                    "The cleaning team that came yesterday did not clean the bathrooms properly. "
                    "The floors still had dust and the windows were not touched. "
                    "I expect better quality for the price I am paying."
                ),
            },
        },
    ]

    for ex in examples:
        with st.expander(ex["label"]):
            st.json(ex["data"])
            if st.button(f"Submit this example", key=ex["label"]):
                with st.spinner("Submitting..."):
                    res = submit_ticket(ex["data"])
                if res.get("success") is not False:
                    st.success(f"Ticket submitted! ID: `{res.get('ticket_id')}`")
                    st.cache_data.clear()
                else:
                    st.error(f"Error: {res.get('error')}")
