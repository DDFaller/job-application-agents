from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from job_application_agents.auto_apply.preprocessor import FormDOMPreprocessor, FormFieldNode, CompressedFormTree


class TestFormDOMPreprocessor(unittest.TestCase):
    def test_prune_raw_html(self):
        raw_html = """
        <html>
        <head>
            <script src="analytics.js">console.log("tracking");</script>
            <style>.btn { color: red; }</style>
        </head>
        <body>
            <header><nav><a href="/">Home</a></nav></header>
            <svg><path d="M10 10"/></svg>
            <form>
                <label>Name</label>
                <input type="text" name="name" />
            </form>
            <footer><p>Copyright 2026</p></footer>
        </body>
        </html>
        """
        pruned = FormDOMPreprocessor.prune_raw_html(raw_html)
        self.assertNotIn("console.log", pruned)
        self.assertNotIn("<style>", pruned)
        self.assertNotIn("<svg>", pruned)
        self.assertNotIn("<nav>", pruned)
        self.assertNotIn("Copyright", pruned)
        self.assertIn("Name", pruned)

    def test_compressed_form_tree_metrics(self):
        fields = [
            FormFieldNode(id="name", name="name", tag="input", type="text", label="Name", required=True),
            FormFieldNode(id="email", name="email", tag="input", type="email", label="Email", required=True),
            FormFieldNode(id="resume", name="resume", tag="input", type="file", label="Resume", required=True),
        ]
        tree = CompressedFormTree(
            url="https://example.com/apply",
            title="Software Engineer Job",
            fields=fields,
            raw_token_estimate=10000,
            compressed_token_estimate=200,
        )
        self.assertAlmostEqual(tree.compression_ratio, 0.98, places=2)
        d = tree.to_dict()
        self.assertEqual(len(d["fields"]), 3)
        self.assertEqual(d["stats"]["compression_ratio_pct"], 98.0)


if __name__ == "__main__":
    unittest.main()
