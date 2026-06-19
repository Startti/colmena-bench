"""Demo #7 — realistic confusable-cluster toolset generator.

The agent is handed N realistic product tools and a NATURAL-LANGUAGE user intent
that never names a tool. The needle tool's whole cluster (~5 tools that are
genuinely similar and easy to confuse) is always present, so the model must
disambiguate by reading summaries/descriptions — not by matching the tool name
or the param shape. Remaining slots are filled with tools from other clusters.

Seeded by a STABLE string so a given (n, seed) is byte-stable across the 6
configs and across processes (fairness), but the scenario rotates across seeds.

Scoring distinguishes three failure modes:
  - selection_ok      : the needle was called at all.
  - wrong_tool_called : a DIFFERENT tool from the needle's cluster was called
                        (the genuine confusion signal).
  - arg_ok / answer_ok: required args matched / expected answer surfaced.
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Curated library: 8 clusters of ~5 realistic, mutually-confusable tools.
# Each cluster declares its needle, a natural-language intent (NO tool name),
# the expected required-arg values (stated verbatim in the intent), and a
# deterministic expected_answer that the needle tool returns.
# ---------------------------------------------------------------------------

_LIBRARY: dict[str, dict[str, Any]] = {
    # 1 -------------------------------------------------------------- refunds
    "refunds_billing": {
        "needle": "create_refund",
        "question": (
            "A customer received a damaged item on order A-1042 and wants their "
            "25 USD back on the card they paid with."
        ),
        "expected_args": {"order_id": "A-1042", "amount_usd": "25", "reason": "damaged"},
        "expected_answer": "REF-A-1042 issued",
        "tools": [
            {
                "name": "create_refund",
                "summary": "Refund money back to the original payment method for an order.",
                "description": (
                    "Issues a cash refund to the card or account the customer "
                    "originally paid with. Use when the customer is owed money back "
                    "for a specific order, e.g. a damaged or wrong item."
                ),
                "params": [
                    {"name": "order_id", "type": "string", "required": True,
                     "description": "The order to refund, e.g. A-1042."},
                    {"name": "amount_usd", "type": "number", "required": True,
                     "description": "Amount to refund in US dollars."},
                    {"name": "reason", "type": "string", "required": True,
                     "description": "Why the refund is being issued.",
                     "enum": ["damaged", "wrong_item", "not_received", "defective", "other"]},
                    {"name": "idempotency_key", "type": "string", "required": False,
                     "description": "Optional unique key to safely retry the refund."},
                ],
            },
            {
                "name": "issue_store_credit",
                "summary": "Grant store credit to a customer's account instead of a cash refund.",
                "description": (
                    "Adds a balance of store credit to the customer's account that "
                    "can be spent on future purchases. Use only when the customer "
                    "agrees to credit rather than money back on their card."
                ),
                "params": [
                    {"name": "customer_id", "type": "string", "required": True,
                     "description": "The customer to credit."},
                    {"name": "amount_usd", "type": "number", "required": True,
                     "description": "Store-credit amount in US dollars."},
                    {"name": "reason", "type": "string", "required": False,
                     "description": "Optional note for why the credit was granted."},
                ],
            },
            {
                "name": "cancel_order",
                "summary": "Cancel an order that has not shipped or been delivered yet.",
                "description": (
                    "Stops fulfillment and voids an order before it ships. Use only "
                    "for orders the customer has not yet received; it cannot reverse a "
                    "completed delivery."
                ),
                "params": [
                    {"name": "order_id", "type": "string", "required": True,
                     "description": "The order to cancel."},
                    {"name": "reason", "type": "string", "required": False,
                     "description": "Optional cancellation reason."},
                ],
            },
            {
                "name": "get_refund_status",
                "summary": "Look up the status of a refund that has already been requested.",
                "description": (
                    "Returns the current state of an existing refund (pending, "
                    "processing, completed). Use only when a refund already exists "
                    "and the customer is asking where it is."
                ),
                "params": [
                    {"name": "order_id", "type": "string", "required": True,
                     "description": "The order whose refund to look up."},
                ],
            },
            {
                "name": "escalate_to_billing",
                "summary": "Hand a complex billing dispute to a human billing specialist.",
                "description": (
                    "Creates a case for the billing team to investigate manually. Use "
                    "for disputes or chargebacks that cannot be resolved with a "
                    "straightforward refund or credit."
                ),
                "params": [
                    {"name": "order_id", "type": "string", "required": True,
                     "description": "The order in dispute."},
                    {"name": "notes", "type": "string", "required": False,
                     "description": "Context for the billing specialist."},
                ],
            },
        ],
    },
    # 2 ------------------------------------------------------------- calendar
    "calendar": {
        "needle": "schedule_meeting",
        "question": (
            "Set up a new 30 minute call with Ana next Tuesday at 3pm."
        ),
        "expected_args": {"attendee": "Ana", "duration_min": "30", "start": "next Tuesday at 3pm"},
        "expected_answer": "MTG-ANA-CONFIRMED",
        "tools": [
            {
                "name": "schedule_meeting",
                "summary": "Book a brand-new meeting on the calendar at a chosen time.",
                "description": (
                    "Creates a new calendar event with a time, duration and an "
                    "attendee. Use when no meeting exists yet and the user wants to "
                    "set one up."
                ),
                "params": [
                    {"name": "attendee", "type": "string", "required": True,
                     "description": "Person to meet with."},
                    {"name": "start", "type": "string", "required": True,
                     "description": "When the meeting starts, e.g. next Tuesday at 3pm."},
                    {"name": "duration_min", "type": "integer", "required": True,
                     "description": "Length of the meeting in minutes."},
                    {"name": "title", "type": "string", "required": False,
                     "description": "Optional meeting title."},
                ],
            },
            {
                "name": "reschedule_meeting",
                "summary": "Move an existing meeting to a different time.",
                "description": (
                    "Changes the start time of a meeting that is already on the "
                    "calendar. Use only when a meeting already exists and needs to be "
                    "moved."
                ),
                "params": [
                    {"name": "meeting_id", "type": "string", "required": True,
                     "description": "The existing meeting to move."},
                    {"name": "new_start", "type": "string", "required": True,
                     "description": "The new start time."},
                ],
            },
            {
                "name": "cancel_meeting",
                "summary": "Remove an existing meeting from the calendar.",
                "description": (
                    "Deletes a scheduled meeting and notifies attendees. Use when an "
                    "existing meeting should no longer happen."
                ),
                "params": [
                    {"name": "meeting_id", "type": "string", "required": True,
                     "description": "The meeting to cancel."},
                ],
            },
            {
                "name": "find_free_slots",
                "summary": "Search for open time slots on the calendar.",
                "description": (
                    "Returns available windows when an attendee is free. Use to "
                    "discover candidate times, not to actually book anything."
                ),
                "params": [
                    {"name": "attendee", "type": "string", "required": True,
                     "description": "Person whose availability to check."},
                    {"name": "duration_min", "type": "integer", "required": False,
                     "description": "Desired slot length in minutes."},
                ],
            },
            {
                "name": "send_calendar_invite",
                "summary": "Email a calendar invite for a meeting that already exists.",
                "description": (
                    "Sends an .ics invitation for an already-created meeting. Use to "
                    "(re)send the invite, not to create the meeting itself."
                ),
                "params": [
                    {"name": "meeting_id", "type": "string", "required": True,
                     "description": "The meeting to send an invite for."},
                    {"name": "attendee", "type": "string", "required": False,
                     "description": "Recipient of the invite."},
                ],
            },
        ],
    },
    # 3 ---------------------------------------------------------------- email
    "email": {
        "needle": "send_email",
        "question": (
            "Email the Q3 report to finance@acme.com right now."
        ),
        "expected_args": {"to": "finance@acme.com", "subject": "Q3 report"},
        "expected_answer": "EMAIL-SENT-OK",
        "tools": [
            {
                "name": "send_email",
                "summary": "Send an email immediately to one or more recipients.",
                "description": (
                    "Composes and sends an email right away. Use when the user wants "
                    "a message delivered now, not saved or scheduled for later."
                ),
                "params": [
                    {"name": "to", "type": "string", "required": True,
                     "description": "Recipient email address."},
                    {"name": "subject", "type": "string", "required": True,
                     "description": "Subject line of the email."},
                    {"name": "body", "type": "string", "required": False,
                     "description": "Optional body text of the email."},
                ],
            },
            {
                "name": "create_draft",
                "summary": "Save an email as a draft without sending it.",
                "description": (
                    "Stores a composed email in drafts for later editing or sending. "
                    "Use when the user wants to prepare a message but not send it yet."
                ),
                "params": [
                    {"name": "to", "type": "string", "required": True,
                     "description": "Intended recipient."},
                    {"name": "subject", "type": "string", "required": True,
                     "description": "Draft subject line."},
                    {"name": "body", "type": "string", "required": False,
                     "description": "Draft body text."},
                ],
            },
            {
                "name": "schedule_email",
                "summary": "Queue an email to be sent automatically at a future time.",
                "description": (
                    "Schedules a message for delivery at a specified later time. Use "
                    "only when the user asks to send later, not immediately."
                ),
                "params": [
                    {"name": "to", "type": "string", "required": True,
                     "description": "Recipient email address."},
                    {"name": "subject", "type": "string", "required": True,
                     "description": "Subject line."},
                    {"name": "send_at", "type": "string", "required": True,
                     "description": "When to send the email."},
                ],
            },
            {
                "name": "reply_to_thread",
                "summary": "Reply within an existing email conversation thread.",
                "description": (
                    "Posts a reply onto an existing email thread, keeping the "
                    "conversation history. Use only when responding to a message that "
                    "already exists."
                ),
                "params": [
                    {"name": "thread_id", "type": "string", "required": True,
                     "description": "The thread to reply to."},
                    {"name": "body", "type": "string", "required": True,
                     "description": "Reply text."},
                ],
            },
            {
                "name": "send_sms",
                "summary": "Send a text message to a phone number.",
                "description": (
                    "Delivers a short SMS text to a mobile number. Use for phone "
                    "texting, not for email delivery."
                ),
                "params": [
                    {"name": "to", "type": "string", "required": True,
                     "description": "Destination phone number."},
                    {"name": "body", "type": "string", "required": True,
                     "description": "Text message content."},
                ],
            },
        ],
    },
    # 4 ------------------------------------------------------------- shipping
    "shipping": {
        "needle": "create_shipment",
        "question": (
            "Ship order A-1042 to the customer with 2_day delivery."
        ),
        "expected_args": {"order_id": "A-1042", "speed": "2_day"},
        "expected_answer": "SHP-A-1042-CREATED",
        "tools": [
            {
                "name": "create_shipment",
                "summary": "Create a new outbound shipment and buy a shipping label for an order.",
                "description": (
                    "Generates a shipment with a chosen delivery speed and produces a "
                    "label. Use when an order needs to actually be shipped to the "
                    "customer."
                ),
                "params": [
                    {"name": "order_id", "type": "string", "required": True,
                     "description": "The order to ship."},
                    {"name": "speed", "type": "string", "required": True,
                     "description": "Delivery speed tier.",
                     "enum": ["overnight", "2_day", "ground", "economy"]},
                    {"name": "carrier", "type": "string", "required": False,
                     "description": "Optional preferred carrier."},
                ],
            },
            {
                "name": "track_shipment",
                "summary": "Look up the current tracking status of a shipment.",
                "description": (
                    "Returns the latest tracking scan and estimated delivery for an "
                    "existing shipment. Use only when a shipment already exists."
                ),
                "params": [
                    {"name": "shipment_id", "type": "string", "required": True,
                     "description": "The shipment to track."},
                ],
            },
            {
                "name": "cancel_shipment",
                "summary": "Cancel a shipment and void its label before pickup.",
                "description": (
                    "Voids an already-created shipping label and cancels the shipment. "
                    "Use only for shipments that have not yet been picked up."
                ),
                "params": [
                    {"name": "shipment_id", "type": "string", "required": True,
                     "description": "The shipment to cancel."},
                ],
            },
            {
                "name": "get_shipping_rate",
                "summary": "Quote the price of shipping an order at a given speed.",
                "description": (
                    "Returns an estimated shipping cost without buying a label. Use to "
                    "price options, not to actually create a shipment."
                ),
                "params": [
                    {"name": "order_id", "type": "string", "required": True,
                     "description": "The order to quote."},
                    {"name": "speed", "type": "string", "required": False,
                     "description": "Delivery speed to price."},
                ],
            },
            {
                "name": "schedule_pickup",
                "summary": "Arrange a carrier pickup for shipments that already have labels.",
                "description": (
                    "Books the carrier to collect packages that already have labels. "
                    "Use after shipments exist, not to create one."
                ),
                "params": [
                    {"name": "carrier", "type": "string", "required": True,
                     "description": "Carrier to schedule pickup with."},
                    {"name": "pickup_date", "type": "string", "required": False,
                     "description": "Requested pickup date."},
                ],
            },
        ],
    },
    # 5 ------------------------------------------------------------- accounts
    "accounts": {
        "needle": "reset_password",
        "question": (
            "User u_88 forgot their password and is locked out — help them get back in."
        ),
        "expected_args": {"user_id": "u_88", "channel": "email"},
        "expected_answer": "PWD-RESET-SENT",
        "tools": [
            {
                "name": "reset_password",
                "summary": "Send a password-reset link so a locked-out user can regain access.",
                "description": (
                    "Triggers a secure password-reset flow and notifies the user so "
                    "they can choose a new password. Use when a user is locked out or "
                    "forgot their password."
                ),
                "params": [
                    {"name": "user_id", "type": "string", "required": True,
                     "description": "The user to reset, e.g. u_88."},
                    {"name": "channel", "type": "string", "required": True,
                     "description": "How to deliver the reset link.",
                     "enum": ["email", "sms"]},
                ],
            },
            {
                "name": "update_email",
                "summary": "Change the email address on a user's account.",
                "description": (
                    "Updates the contact email tied to an account. Use when a user "
                    "wants a different email on file, not when they are locked out."
                ),
                "params": [
                    {"name": "user_id", "type": "string", "required": True,
                     "description": "The user to update."},
                    {"name": "new_email", "type": "string", "required": True,
                     "description": "The new email address."},
                ],
            },
            {
                "name": "deactivate_account",
                "summary": "Disable a user's account so they can no longer sign in.",
                "description": (
                    "Suspends an account and revokes its access. Use to lock someone "
                    "out on purpose, never to restore access."
                ),
                "params": [
                    {"name": "user_id", "type": "string", "required": True,
                     "description": "The user to deactivate."},
                ],
            },
            {
                "name": "get_user_profile",
                "summary": "Fetch a user's profile and account details.",
                "description": (
                    "Returns read-only profile information for a user. Use to look up "
                    "details, not to change anything."
                ),
                "params": [
                    {"name": "user_id", "type": "string", "required": True,
                     "description": "The user to look up."},
                ],
            },
            {
                "name": "grant_admin_role",
                "summary": "Give a user administrator privileges.",
                "description": (
                    "Elevates an account to an admin role with extra permissions. Use "
                    "only for intentional privilege grants."
                ),
                "params": [
                    {"name": "user_id", "type": "string", "required": True,
                     "description": "The user to promote."},
                    {"name": "role", "type": "string", "required": False,
                     "description": "Optional specific admin role."},
                ],
            },
        ],
    },
    # 6 -------------------------------------------------------------- support
    "support": {
        "needle": "create_ticket",
        "question": (
            "Log a new bug report from customer c_31 about the checkout page crashing."
        ),
        "expected_args": {"customer_id": "c_31", "subject": "checkout page crashing", "category": "bug"},
        "expected_answer": "TKT-C31-OPENED",
        "tools": [
            {
                "name": "create_ticket",
                "summary": "Open a brand-new support ticket for a customer issue.",
                "description": (
                    "Creates a new support case attached to a customer, with a subject "
                    "and category. Use when logging a fresh issue that has no existing "
                    "ticket."
                ),
                "params": [
                    {"name": "customer_id", "type": "string", "required": True,
                     "description": "The customer reporting the issue, e.g. c_31."},
                    {"name": "subject", "type": "string", "required": True,
                     "description": "Short description of the problem."},
                    {"name": "category", "type": "string", "required": True,
                     "description": "Type of issue.",
                     "enum": ["bug", "billing", "how_to", "feature_request", "other"]},
                ],
            },
            {
                "name": "close_ticket",
                "summary": "Mark an existing support ticket as resolved and closed.",
                "description": (
                    "Closes a ticket once the issue is handled. Use only on a ticket "
                    "that already exists."
                ),
                "params": [
                    {"name": "ticket_id", "type": "string", "required": True,
                     "description": "The ticket to close."},
                ],
            },
            {
                "name": "escalate_ticket",
                "summary": "Raise an existing ticket's priority and route it to a senior team.",
                "description": (
                    "Escalates an open ticket to higher-tier support. Use only on a "
                    "ticket that already exists."
                ),
                "params": [
                    {"name": "ticket_id", "type": "string", "required": True,
                     "description": "The ticket to escalate."},
                    {"name": "priority", "type": "string", "required": False,
                     "description": "Target priority level."},
                ],
            },
            {
                "name": "add_ticket_comment",
                "summary": "Add a comment or note to an existing support ticket.",
                "description": (
                    "Appends a comment to an existing ticket's history. Use to update "
                    "a ticket, not to create one."
                ),
                "params": [
                    {"name": "ticket_id", "type": "string", "required": True,
                     "description": "The ticket to comment on."},
                    {"name": "comment", "type": "string", "required": True,
                     "description": "The comment text."},
                ],
            },
            {
                "name": "reassign_ticket",
                "summary": "Move an existing ticket to a different agent or queue.",
                "description": (
                    "Changes the owner of an existing ticket. Use only when a ticket "
                    "already exists and needs a new assignee."
                ),
                "params": [
                    {"name": "ticket_id", "type": "string", "required": True,
                     "description": "The ticket to reassign."},
                    {"name": "assignee", "type": "string", "required": False,
                     "description": "New owner of the ticket."},
                ],
            },
        ],
    },
    # 7 ------------------------------------------------------------- payments
    "payments": {
        "needle": "charge_card",
        "question": (
            "Charge the customer's card 49.99 for the subscription renewal of customer c_77."
        ),
        "expected_args": {"customer_id": "c_77", "amount_usd": "49.99"},
        "expected_answer": "CHG-C77-CAPTURED",
        "tools": [
            {
                "name": "charge_card",
                "summary": "Charge a customer's saved card for a given amount right now.",
                "description": (
                    "Immediately captures a payment on the customer's stored card. Use "
                    "when money should be collected now, e.g. a subscription renewal."
                ),
                "params": [
                    {"name": "customer_id", "type": "string", "required": True,
                     "description": "The customer to charge."},
                    {"name": "amount_usd", "type": "number", "required": True,
                     "description": "Amount to charge in US dollars."},
                    {"name": "description", "type": "string", "required": False,
                     "description": "Optional statement descriptor."},
                ],
            },
            {
                "name": "create_invoice",
                "summary": "Create an invoice for the customer to pay later.",
                "description": (
                    "Generates an unpaid invoice billed to the customer. Use when you "
                    "want the customer to pay later, not to charge them now."
                ),
                "params": [
                    {"name": "customer_id", "type": "string", "required": True,
                     "description": "The customer to bill."},
                    {"name": "amount_usd", "type": "number", "required": True,
                     "description": "Invoice amount in US dollars."},
                ],
            },
            {
                "name": "refund_payment",
                "summary": "Return funds from a previously captured payment.",
                "description": (
                    "Reverses a charge that has already been collected. Use to give "
                    "money back, never to collect it."
                ),
                "params": [
                    {"name": "payment_id", "type": "string", "required": True,
                     "description": "The captured payment to refund."},
                    {"name": "amount_usd", "type": "number", "required": False,
                     "description": "Optional partial refund amount."},
                ],
            },
            {
                "name": "void_invoice",
                "summary": "Cancel an unpaid invoice so it no longer needs to be paid.",
                "description": (
                    "Voids an outstanding invoice. Use only on an invoice that exists "
                    "and has not been paid."
                ),
                "params": [
                    {"name": "invoice_id", "type": "string", "required": True,
                     "description": "The invoice to void."},
                ],
            },
            {
                "name": "get_payment_status",
                "summary": "Check whether a payment has been captured, pending or failed.",
                "description": (
                    "Returns the state of an existing payment. Use to look up status, "
                    "not to move money."
                ),
                "params": [
                    {"name": "payment_id", "type": "string", "required": True,
                     "description": "The payment to look up."},
                ],
            },
        ],
    },
    # 8 ------------------------------------------------------------ inventory
    "inventory": {
        "needle": "adjust_stock",
        "question": (
            "We just received 50 new units of SKU-991 — add them to stock."
        ),
        "expected_args": {"sku": "SKU-991", "delta": "50"},
        "expected_answer": "STK-SKU-991-ADJUSTED",
        "tools": [
            {
                "name": "adjust_stock",
                "summary": "Increase or decrease the on-hand stock count for a SKU.",
                "description": (
                    "Applies a delta to the recorded quantity on hand for a SKU. Use "
                    "to correct or add inventory you physically have, e.g. a received "
                    "shipment."
                ),
                "params": [
                    {"name": "sku", "type": "string", "required": True,
                     "description": "The stock-keeping unit, e.g. SKU-991."},
                    {"name": "delta", "type": "integer", "required": True,
                     "description": "Change in units; positive to add, negative to remove."},
                    {"name": "reason", "type": "string", "required": False,
                     "description": "Optional reason for the adjustment."},
                ],
            },
            {
                "name": "get_stock_level",
                "summary": "Look up the current quantity on hand for a SKU.",
                "description": (
                    "Returns the recorded inventory count for a SKU. Use to read the "
                    "level, not to change it."
                ),
                "params": [
                    {"name": "sku", "type": "string", "required": True,
                     "description": "The SKU to look up."},
                ],
            },
            {
                "name": "create_purchase_order",
                "summary": "Order more units of a SKU from a supplier.",
                "description": (
                    "Creates a purchase order to buy inventory from a vendor. Use to "
                    "procure stock you do not yet have, not to record received goods."
                ),
                "params": [
                    {"name": "sku", "type": "string", "required": True,
                     "description": "The SKU to reorder."},
                    {"name": "quantity", "type": "integer", "required": True,
                     "description": "Units to order from the supplier."},
                ],
            },
            {
                "name": "transfer_stock",
                "summary": "Move stock of a SKU from one warehouse location to another.",
                "description": (
                    "Relocates existing inventory between locations without changing "
                    "the total count. Use for internal moves, not for receiving."
                ),
                "params": [
                    {"name": "sku", "type": "string", "required": True,
                     "description": "The SKU to move."},
                    {"name": "from_location", "type": "string", "required": True,
                     "description": "Source location."},
                    {"name": "to_location", "type": "string", "required": True,
                     "description": "Destination location."},
                ],
            },
            {
                "name": "set_reorder_point",
                "summary": "Configure the threshold at which a SKU triggers reordering.",
                "description": (
                    "Sets the low-stock threshold that flags a SKU for reorder. Use to "
                    "configure policy, not to change the actual count."
                ),
                "params": [
                    {"name": "sku", "type": "string", "required": True,
                     "description": "The SKU to configure."},
                    {"name": "threshold", "type": "integer", "required": False,
                     "description": "Reorder-point quantity."},
                ],
            },
        ],
    },
}

_CLUSTER_NAMES = sorted(_LIBRARY.keys())


def _clone_tool(cluster_name: str, tool: dict, is_needle: bool, answer: str) -> dict:
    """Deep-copy a library tool into a self-contained spec entry."""
    params = [
        {
            "name": p["name"],
            "type": p["type"],
            "required": p["required"],
            "description": p["description"],
            **({"enum": list(p["enum"])} if "enum" in p else {}),
        }
        for p in tool["params"]
    ]
    return {
        "name": tool["name"],
        "summary": tool["summary"],
        "description": tool["description"],
        "params": params,
        "cluster": cluster_name,
        "is_needle": is_needle,
        "answer": answer if is_needle else "not applicable",
    }


def generate_toolset(n: int, seed: int) -> dict:
    """Build a byte-stable toolset of N realistic tools around one needle.

    The needle's full cluster (~5 confusable tools) is always present; remaining
    slots are filled with tools sampled from other clusters. Tool order is
    shuffled so the needle lands at a random position.
    """
    rng = random.Random(f"{n}-{seed}")
    cluster_name = _CLUSTER_NAMES[rng.randrange(len(_CLUSTER_NAMES))]
    cluster = _LIBRARY[cluster_name]
    needle_name = cluster["needle"]
    answer = cluster["expected_answer"]

    tools: list[dict] = []
    used: set[str] = set()

    # 1) Always include the whole needle cluster (the confusers).
    for tool in cluster["tools"]:
        tools.append(_clone_tool(cluster_name, tool, tool["name"] == needle_name, answer))
        used.add(tool["name"])

    # 2) Fill remaining slots from OTHER clusters.
    if len(tools) > n:
        # n smaller than a cluster: keep the needle, then random cluster-mates.
        keep = [t for t in tools if t["is_needle"]]
        others = [t for t in tools if not t["is_needle"]]
        rng.shuffle(others)
        tools = keep + others[: max(0, n - 1)]
    else:
        filler_pool: list[tuple[str, dict]] = []
        for cn in _CLUSTER_NAMES:
            if cn == cluster_name:
                continue
            for tool in _LIBRARY[cn]["tools"]:
                filler_pool.append((cn, tool))
        rng.shuffle(filler_pool)
        i = 0
        while len(tools) < n and i < len(filler_pool):
            cn, tool = filler_pool[i]
            i += 1
            if tool["name"] in used:
                continue
            used.add(tool["name"])
            tools.append(_clone_tool(cn, tool, False, "not applicable"))

    rng.shuffle(tools)

    expected_args = dict(cluster["expected_args"])

    return {
        "n_tools": n,
        "seed": seed,
        "needle": needle_name,
        "cluster": cluster_name,
        "expected_args": expected_args,
        "expected_answer": answer,
        "question": cluster["question"],
        "tools": tools,
    }


def _clone_session_tool(cluster_name: str, tool: dict) -> dict:
    """Deep-copy a library tool for a fixed session toolset.

    Same shape as ``generate_toolset`` tools but WITHOUT ``is_needle``/``answer``,
    since the needle varies per turn in a multi-turn session.
    """
    params = [
        {
            "name": p["name"],
            "type": p["type"],
            "required": p["required"],
            "description": p["description"],
            **({"enum": list(p["enum"])} if "enum" in p else {}),
        }
        for p in tool["params"]
    ]
    return {
        "name": tool["name"],
        "summary": tool["summary"],
        "description": tool["description"],
        "params": params,
        "cluster": cluster_name,
    }


def generate_session(n_tools: int = 30, n_turns: int = 10, seed: int = 0) -> dict:
    """Build a byte-stable multi-turn session: one FIXED toolset + per-turn requests.

    Models a realistic agent holding ~30 tools across a conversation of ~10
    user requests. Whole clusters are included so every turn's needle has its
    confusers present in the fixed set. ``n_tools`` is a TARGET: the result is
    trimmed/padded to land within a couple of tools of it (we pick whole
    clusters of ~5 tools, then add/remove non-needle filler from other clusters
    to hit it exactly when possible).

    Each turn rotates through the included clusters (seeded) and reuses that
    cluster's designated needle, natural-language question, expected_args and
    expected_answer from ``_LIBRARY``. Same (n_tools, n_turns, seed) is
    byte-stable across processes.
    """
    rng = random.Random(f"{n_tools}-{n_turns}-{seed}")

    # How many whole clusters to include: ceil(n_tools / ~5), bounded by what we
    # have, and at least enough that turns can span several clusters.
    per_cluster = 5  # every cluster in _LIBRARY has 5 tools
    n_clusters = (n_tools + per_cluster - 1) // per_cluster
    n_clusters = max(1, min(n_clusters, len(_CLUSTER_NAMES)))

    shuffled = list(_CLUSTER_NAMES)
    rng.shuffle(shuffled)
    included = shuffled[:n_clusters]

    # Build the fixed toolset from whole clusters. Track which tool names are
    # needles so trimming never removes one.
    tools: list[dict] = []
    needle_names: set[str] = set()
    for cn in included:
        cluster = _LIBRARY[cn]
        needle_names.add(cluster["needle"])
        for tool in cluster["tools"]:
            tools.append(_clone_session_tool(cn, tool))

    # Trim filler (non-needle) tools down to the target, or pad from other
    # clusters up to the target. n_tools is a target, not a hard guarantee.
    if len(tools) > n_tools:
        removable = [
            i for i, t in enumerate(tools) if t["name"] not in needle_names
        ]
        rng.shuffle(removable)
        to_remove = set(removable[: len(tools) - n_tools])
        tools = [t for i, t in enumerate(tools) if i not in to_remove]
    elif len(tools) < n_tools:
        used = {t["name"] for t in tools}
        filler_pool: list[tuple[str, dict]] = []
        for cn in _CLUSTER_NAMES:
            if cn in included:
                continue
            for tool in _LIBRARY[cn]["tools"]:
                filler_pool.append((cn, tool))
        rng.shuffle(filler_pool)
        i = 0
        while len(tools) < n_tools and i < len(filler_pool):
            cn, tool = filler_pool[i]
            i += 1
            if tool["name"] in used:
                continue
            used.add(tool["name"])
            tools.append(_clone_session_tool(cn, tool))

    rng.shuffle(tools)

    # Build turns by rotating through the included clusters so turns vary and
    # ideally cover different clusters; repeats are fine when n_turns > clusters.
    turn_clusters = list(included)
    rng.shuffle(turn_clusters)
    turns: list[dict] = []
    for i in range(n_turns):
        cn = turn_clusters[i % len(turn_clusters)]
        cluster = _LIBRARY[cn]
        turns.append({
            "turn": i + 1,
            "question": cluster["question"],
            "needle": cluster["needle"],
            "cluster": cn,
            "expected_args": dict(cluster["expected_args"]),
            "expected_answer": cluster["expected_answer"],
        })

    return {
        "n_tools": n_tools,
        "n_turns": n_turns,
        "seed": seed,
        "tools": tools,
        "turns": turns,
    }


def log_tool_call(tool_name: str, args: dict) -> None:
    path = os.environ.get("BENCH_TOOLCALL_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": tool_name, "args": args, "ts": time.time()}) + "\n")


def read_tool_calls(path: "str | Path") -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def score(spec: dict, tool_calls: list[dict], final_answer: str) -> dict:
    """Score a run against the spec.

    selection_ok      : the needle tool was called.
    wrong_tool_called : a tool from the needle's cluster OTHER than the needle
                        was called (the confusion signal).
    arg_ok            : the needle was called with all expected_args matching.
    answer_ok         : expected_answer appears in the final answer.
    """
    needle = spec["needle"]
    cluster = spec["cluster"]
    cluster_mates = {
        t["name"] for t in spec["tools"]
        if t.get("cluster") == cluster and t["name"] != needle
    }

    called_needle = [c for c in tool_calls if c.get("tool") == needle]
    selection_ok = len(called_needle) > 0
    wrong_tool_called = any(c.get("tool") in cluster_mates for c in tool_calls)

    arg_ok = any(
        all(str(c.get("args", {}).get(k)) == str(v) for k, v in spec["expected_args"].items())
        for c in called_needle
    )
    answer_ok = spec["expected_answer"] in (final_answer or "")

    return {
        "selection_ok": selection_ok,
        "arg_ok": arg_ok,
        "answer_ok": answer_ok,
        "wrong_tool_called": wrong_tool_called,
    }


def score_turn(
    session: dict,
    turn_idx: int,
    tool_calls_for_turn: list[dict],
    final_answer: str,
) -> dict:
    """Score a single turn of a multi-turn session.

    Builds a per-turn spec (the turn's needle/cluster/expected_args/answer plus
    the session's fixed toolset) and delegates to ``score`` so the failure-mode
    semantics — selection_ok / wrong_tool_called / arg_ok / answer_ok — match
    exactly.
    """
    turn = session["turns"][turn_idx]
    spec = {
        "needle": turn["needle"],
        "cluster": turn["cluster"],
        "expected_args": turn["expected_args"],
        "expected_answer": turn["expected_answer"],
        "tools": session["tools"],
    }
    return score(spec, tool_calls_for_turn, final_answer)
