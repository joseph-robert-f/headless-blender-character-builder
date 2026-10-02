"""Tests for the limited documentation-language checker, not for STE conformity."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("documentation_language", str(ROOT / "scripts/check-documentation-language"))
spec = importlib.util.spec_from_loader(loader.name, loader)
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
loader.exec_module(checker)


class LanguageCheckTests(unittest.TestCase):
    def rules(self, text):
        return {finding.rule for finding in checker.inspect_text("example.md", text)}

    def test_preserve_fenced_commands(self):
        self.assertEqual(self.rules("```sh\npython -c 'import sys; print(sys.version)'\n```\n"), set())

    def test_preserve_inline_identifiers(self):
        self.assertEqual(self.rules("Use `python -c 'import sys; print(sys.version)'`.\n"), set())

    def test_prose_semicolon(self):
        self.assertIn("semicolon", self.rules("Stop the server; keep the log.\n"))

    def test_contraction(self):
        self.assertIn("contraction", self.rules("Do not use it if it isn't ready.\n"))

    def test_possessive_is_not_contraction(self):
        self.assertNotIn("contraction", self.rules("Read the user's request.\n"))

    def test_paragraph_limit(self):
        self.assertIn("paragraph", self.rules(" ".join(["The file exists."] * 7)))

    def test_description_limit(self):
        self.assertIn("sentence", self.rules("The " + " ".join(["item"] * 25) + "."))

    def test_instruction_limit(self):
        self.assertIn("sentence", self.rules("Use " + " ".join(["item"] * 20) + "."))

    def test_parentheses_and_code_are_one_element(self):
        self.assertEqual(checker.plain("Use `one two` (three four)."), "Use IDENTIFIER PAREN.")

    def test_approved_ing_adjective_is_not_progressive(self):
        self.assertNotIn("complex-verb", self.rules("The file is missing."))

    def test_complex_verb_locator(self):
        self.assertIn("complex-verb", self.rules("The server has stopped.\n"))

    def test_unregistered_historical_region_is_a_scope_error(self):
        text = "<!-- ste-preserve:start historical record -->\nOld text.\n<!-- ste-preserve:end -->"
        self.assertTrue(checker.historical_markers("file.md", text, False))

    def test_unclosed_historical_region_is_a_scope_error(self):
        text = "<!-- ste-preserve:start historical record -->\nOld text."
        self.assertTrue(checker.historical_markers("file.md", text, True))

    def test_malformed_historical_region_is_a_scope_error(self):
        self.assertTrue(checker.historical_markers("file.md", "<!-- ste-preserve:start historical", True))

    def test_marked_historical_region_is_not_rewritten(self):
        text = "<!-- ste-preserve:start historical record -->\nOld text; keep it.\n<!-- ste-preserve:end -->\nRead the current guide."
        self.assertEqual(self.rules(text), set())

    def test_current_prose_after_history_stays_in_scope(self):
        text = "<!-- ste-preserve:start historical record -->\nOld text.\n<!-- ste-preserve:end -->\nStop; keep the log."
        self.assertIn("semicolon", self.rules(text))

    def test_table_cells_are_independent(self):
        self.assertIn("semicolon", self.rules("| Item | Read this; then stop. |\n"))

    def test_list_items_are_independent(self):
        self.assertNotIn("paragraph", self.rules("\n".join(["- The file exists."] * 7)))


if __name__ == "__main__":
    unittest.main()
