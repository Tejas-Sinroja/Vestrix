from .pricing import price_items
from .repository import OrderRepository


class CheckoutService:
    def __init__(self):
        self.repo = OrderRepository()

    def checkout(self, user_id, items):
        priced = price_items(items)
        total = round(sum(line["subtotal"] for line in priced), 2)
        order = {"user_id": user_id, "lines": priced, "total": total}
        order_id = self.repo.save(order)
        order["id"] = order_id
        return order
