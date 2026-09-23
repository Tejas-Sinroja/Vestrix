from .service import CheckoutService
from .validation import validate_request


def handle_checkout(request):
    payload = validate_request(request)
    service = CheckoutService()
    order = service.checkout(payload["user_id"], payload["items"])
    return {"status": "ok", "order_id": order["id"], "total": order["total"]}
