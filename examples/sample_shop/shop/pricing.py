TAX_RATE = 0.08
PRICES = {"A1": 19.99, "B7": 5.50}


def price_items(items):
    lines = []
    for item in items:
        unit = lookup_price(item["sku"])
        lines.append({"sku": item["sku"], "qty": item["qty"], "subtotal": apply_tax(unit * item["qty"])})
    return lines


def lookup_price(sku):
    return PRICES.get(sku, 0.0)


def apply_tax(amount):
    return round(amount * (1 + TAX_RATE), 2)
