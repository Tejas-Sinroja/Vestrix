from . import handle_checkout
from .router import router


@router.post("/checkout")
def checkout_endpoint(body):
    """HTTP entry point: POST /checkout."""
    result = handle_checkout(body)
    return {"code": 200, "json": result}
