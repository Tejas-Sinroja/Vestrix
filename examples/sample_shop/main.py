from shop import web  # noqa: F401  (registers routes)
from shop.router import router

if __name__ == "__main__":
    request = {"user_id": 42, "items": [{"sku": "a1 ", "qty": 2}, {"sku": "B7", "qty": 1}]}
    print(router.dispatch("POST", "/checkout", request))
