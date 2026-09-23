def validate_request(request):
    if "user_id" not in request or not request.get("items"):
        raise ValueError("user_id and items are required")
    items = [normalize_item(i) for i in request["items"]]
    return {"user_id": int(request["user_id"]), "items": items}


def normalize_item(item):
    return {"sku": item["sku"].strip().upper(), "qty": max(1, int(item.get("qty", 1)))}
