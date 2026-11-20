# Order record fields

- `order_id`: our order number, always `SO-` plus digits.
- `status`: order state code. `NEW` = placed, not paid. `PAI` = paid. `SHP` = shipped, not yet delivered. `DLV` = delivered. `CAN` = cancelled.
- `placed_at`: when the customer placed the order, UTC, ISO 8601.
- `customer.tier`: loyalty tier, one of `standard`, `silver`, `gold`.
- `customer.email_opt_in`: whether the customer agreed to marketing email.
- `lines[]`: one entry per product. `qty` is the count ordered. `unit_price_minor` is the price of one unit in minor currency units (cents), before discount. A price of 0 means a free promotional item.
- `currency`: ISO 4217 code for every amount in the record.
- `discount_pct`: percent off the sum of line totals. Shipping is never discounted.
- `shipping_minor`: shipping charge in minor units.
- `promised_by`: last delivery date promised to the customer (local date).
- `delivered_at`: when it was delivered, UTC; `null` until delivered.
