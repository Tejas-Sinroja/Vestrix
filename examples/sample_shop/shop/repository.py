import json
import uuid


class BaseRepository:
    """Shared persistence helpers."""

    def __init__(self):
        self.rows = []

    def _serialize(self, obj):
        return json.dumps(obj, sort_keys=True)


class OrderRepository(BaseRepository):
    """Stores orders in memory (stand-in for a database)."""

    def save(self, order):
        order_id = uuid.uuid4().hex[:8]
        record = self._serialize({"id": order_id, **order})
        self.rows.append(record)
        return order_id
