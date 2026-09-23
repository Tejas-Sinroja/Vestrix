import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vestrix import Project, build_html  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_shop"


class SampleShopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project(SAMPLE)

    def resolved(self, fn, text):
        f = self.p.funcs[fn]
        return next(c for c in f.calls if c.text == text).resolved

    def test_modules_and_entries(self):
        self.assertIn("shop.api", self.p.modules)
        self.assertEqual(self.p.funcs["shop.web.checkout_endpoint"].entry["label"], "POST /checkout")
        self.assertEqual(self.p.funcs["main.<module>"].entry["kind"], "main")

    def test_resolution(self):
        self.assertEqual(self.resolved("shop.api.handle_checkout", "service.checkout"),
                         "shop.service.CheckoutService.checkout")          # local type inference
        self.assertEqual(self.resolved("shop.service.CheckoutService.checkout", "self.repo.save"),
                         "shop.repository.OrderRepository.save")            # self.attr type from __init__
        self.assertEqual(self.resolved("shop.repository.OrderRepository.save", "self._serialize"),
                         "shop.repository.BaseRepository._serialize")      # inherited method
        self.assertEqual(self.resolved("shop.web.checkout_endpoint", "handle_checkout"),
                         "shop.api.handle_checkout")                       # package re-export
        self.assertEqual(self.resolved("main.<module>", "router.dispatch"),
                         "shop.router.Router.dispatch")                    # module-level instance
        self.assertIsNone(self.resolved("shop.pricing.apply_tax", "round"))

    def test_bindings_skip_self(self):
        f = self.p.funcs["shop.repository.OrderRepository.save"]
        call = next(c for c in f.calls if c.text == "self._serialize")
        self.assertEqual([p for _, p in call.bindings], ["obj"])

    def test_value_crosses_functions(self):
        start = self.p.gid("shop.web.checkout_endpoint", "var:body")
        reached = {g for g, _, _ in self.p.trace(start)}
        for g in ("shop.api.handle_checkout::var:request",
                  "shop.service.CheckoutService.checkout::var:items",
                  "shop.pricing.apply_tax::var:amount",
                  "shop.repository.BaseRepository._serialize::var:obj",
                  "shop.web.checkout_endpoint::return"):
            self.assertIn(g, reached)

    def test_backward_trace(self):
        start = self.p.gid("shop.pricing.apply_tax", "var:amount")
        reached = {g for g, _, _ in self.p.trace(start, "backward")}
        self.assertIn("shop.pricing.price_items::var:unit", reached)
        self.assertIn("shop.web.checkout_endpoint::var:body", reached)

    def test_html_is_self_contained(self):
        page = build_html(self.p)
        self.assertNotIn("__CODEFLOW_DATA__", page)
        self.assertNotIn("http://", page.split("<script id=\"cf-data\"")[0].replace("http://www.w3.org", ""))
        self.assertIn('"shop.api.handle_checkout"', page)


class ServerHelpersTests(unittest.TestCase):
    def test_list_dir_detects_project_markers(self):
        from vestrix.server import list_dir
        d = list_dir(str(ROOT / "examples"))
        shop = next(x for x in d["dirs"] if x["name"] == "sample_shop")
        self.assertEqual(shop["py"], 1)                       # main.py at the top level
        self.assertGreaterEqual(d["py_total"], 9)

    def test_landing_page_renders(self):
        from vestrix.render import empty_data
        page = build_html(data=empty_data(ROOT))
        self.assertIn('"landing":true', page)


class CircularImportTests(unittest.TestCase):
    def test_cycle_kinds(self):
        import tempfile
        files = {
            "a.py": "import b\n\ndef fa():\n    return b.fb()\n",
            "b.py": "from a import fa\n\ndef fb():\n    return 1\n",                    # a <-> b at import time
            "c.py": "import d\n",
            "d.py": "def fd():\n    import c\n    return c\n",                          # c <-> d only via a function
            "e.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import f\n",
            "f.py": "import e\n",                                                    # typing-only: not a cycle
        }
        with tempfile.TemporaryDirectory() as d:
            for name, src in files.items():
                Path(d, name).write_text(src)
            cycles = {frozenset(c["modules"]): c for c in Project(d).import_cycles()}
        self.assertEqual(cycles[frozenset({"a", "b"})]["severity"], "import-time")
        self.assertEqual(cycles[frozenset({"c", "d"})]["severity"], "deferred")
        self.assertNotIn(frozenset({"e", "f"}), cycles)
        path = cycles[frozenset({"a", "b"})]["path"]
        self.assertEqual(path[0], path[-1])
        self.assertEqual(len(path), 3)

    def test_sample_has_no_cycles(self):
        self.assertEqual(Project(SAMPLE).import_cycles(), [])


class EdgeCaseTests(unittest.TestCase):
    def test_single_file_and_syntax_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            Path(d, "ok.py").write_text("def a(x):\n    return b(x)\n\ndef b(y):\n    return y * 2\n")
            Path(d, "bad.py").write_text("def broken(:\n")
            p = Project(d)
            self.assertEqual(len(p.errors), 1)
            self.assertEqual(p.funcs["ok.a"].calls[0].resolved, "ok.b")
            reached = {g for g, _, _ in p.trace("ok.a::var:x")}
            self.assertIn("ok.b::var:y", reached)
            self.assertIn("ok.a::return", reached)


if __name__ == "__main__":
    unittest.main()
