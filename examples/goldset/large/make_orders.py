"""Write examples/goldset/large/sources/orders.json: a large, realistic order export (seeded, so it is the same every time)."""

import json
import random
import sys
from pathlib import Path

N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
rnd = random.Random(7)
SKUS = {"KB-210": 4950, "MS-044": 2900, "HD-310": 8900, "CB-001": 0, "MN-270": 23900, "DK-050": 15900}
STATUS = ["DLV"] * 55 + ["SHP"] * 25 + ["PAI"] * 12 + ["NEW"] * 6 + ["CAN"] * 2
orders = []
for i in range(N):
    status = rnd.choice(STATUS)
    o = {
        "order_id": f"SO-{2000 + i}",
        "status": status,
        "placed_at": f"2026-09-{rnd.randint(1, 30):02d}T{rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:00Z",
        "customer": {"id": f"C-{rnd.randint(1, 300)}", "tier": rnd.choice(["standard"] * 6 + ["silver"] * 3 + ["gold"]),
                     "email_opt_in": rnd.random() < 0.4},
        "lines": [{"sku": s, "qty": rnd.randint(1, 4), "unit_price_minor": SKUS[s]} for s in rnd.sample(list(SKUS), rnd.randint(1, 4))],
        "currency": rnd.choice(["EUR"] * 9 + ["GBP"]),
        "discount_pct": rnd.choice([0, 0, 0, 5, 10, 15]),
        "shipping_minor": rnd.choice([0, 495, 995]),
        "promised_by": f"2026-10-{rnd.randint(1, 28):02d}",
        "delivered_at": f"2026-10-{rnd.randint(1, 28):02d}T12:00:00Z" if status == "DLV" else None,
    }
    if rnd.random() < 0.05:
        o["coupon"] = rnd.choice(["WELCOME5", "AUTUMN10"])
    if status == "CAN":
        o["cancel_reason"] = rnd.choice(["customer_request", "payment_failed"])
    orders.append(o)
out = Path(__file__).parent / "sources" / "orders.json"
out.write_text(json.dumps({"export": {"generated_at": "2026-10-26T00:00:00Z", "store": "EU-1"}, "orders": orders}, indent=1))
print(f"{out}: {N} orders, {out.stat().st_size // 1024} KiB")
