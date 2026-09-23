class Router:
    """Tiny stand-in for a FastAPI/Flask router so the example runs with no dependencies."""

    def __init__(self):
        self.routes = {}

    def post(self, path):
        def register(fn):
            self.routes[("POST", path)] = fn
            return fn
        return register

    def dispatch(self, method, path, body):
        handler = self.routes[(method, path)]
        return handler(body)


router = Router()
