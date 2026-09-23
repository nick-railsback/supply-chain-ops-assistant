---
name: triage
description: |
  Diagnose a stuck order, propose the next action, and draft approval-ready customer comms.
  Reads live triage context through the read-only triage MCP server; never mutates OMS, WMS, or TMS state.
  Every proposed action or comms draft needs explicit human approval before anything is sent or executed.
tools:
  - list_stuck_orders
  - get_order_triage_context
  - get_carrier_stats
trigger: manual
---

# triage

Diagnose a stuck order, propose the next action, and draft comms a human can
review and send — without ever mutating OMS, WMS, or TMS state. This skill
pairs with the `triage` MCP server: every read below is a tool call against
that server's read-only API, validated against the documented monō foundry
contract at the pinned commit (see the `mono-foundry-context` reference pack).

## Procedure

1. **Find stuck orders.** Call `list_stuck_orders` for the current candidate
   set, bounded by the server's own cap. If the user already named a specific
   order, skip straight to step 2.
2. **Pull full context.** Call `get_order_triage_context` for the order under
   triage. This is the entire evidence base: order, line items, exceptions,
   shipment, and inventory.
3. **Diagnose root cause.** The server deliberately returns no diagnosis
   field — this step is the skill's own reasoning over the context payload,
   not a tool call. State which of the taxonomy's three categories
   (`inventory`, `carrier`, `address_exception`) the evidence points to, and
   why, citing the specific exception, shipment, or inventory fields that
   support it.
4. **Propose the next action.** A concrete, human-reviewable next step. The
   server exposes no write path at all, so "propose" is the only verb
   available here — nothing in this procedure executes a mutation.
5. **Draft comms.** Customer-facing language for the proposed resolution,
   ready for a human to review and send.
6. **Present both for approval.** The proposed action and the draft comms go
   to the human together. The skill does not send, execute, or mark anything
   resolved on its own — every outcome waits on explicit human approval.

## Validation

This procedure is validated against the documented contract at the pinned
commit, not against a live monō foundry session.
