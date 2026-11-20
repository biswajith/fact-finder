---
applies_to: ["*.json"]
output_format: json
---
Given an order number, summarise that order from the export for the support dashboard. Return only a JSON object with these keys:
- "order_id": string
- "status": the status in plain English (e.g. "shipped")
- "items": total number of units ordered
- "amount_due": total the customer pays, in major units (e.g. 12.34), after discount and including shipping
- "currency": ISO code
- "late": true if not delivered and today (2026-10-26) is after promised_by, else false
