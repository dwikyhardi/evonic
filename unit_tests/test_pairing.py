"""Tests for backend.pairing — Pairing Code Generator (XXX-XXX)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.pairing import generate_pair_code, format_pair_code, validate_pair_code


class TestGeneratePairCode(unittest.TestCase):
    """Tests for generate_pair_code()."""

    VALID_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

    def test_returns_6_characters(self):
        code = generate_pair_code()
        self.assertEqual(len(code), 6)

    def test_contains_only_uppercase_and_digits(self):
        for _ in range(100):
            code = generate_pair_code()
            for ch in code:
                self.assertIn(ch, self.VALID_CHARS)

    def test_no_two_codes_are_identical_in_500_runs(self):
        codes = {generate_pair_code() for _ in range(500)}
        self.assertEqual(len(codes), 500)

    def test_consecutive_codes_do_not_collide_frequently(self):
        for _ in range(5):
            codes = {generate_pair_code() for _ in range(100)}
            self.assertEqual(len(codes), 100)


class TestFormatPairCode(unittest.TestCase):
    """Tests for format_pair_code()."""

    def test_formats_correctly(self):
        self.assertEqual(format_pair_code("ABC123"), "ABC-123")

    def test_formats_any_6_char_input(self):
        self.assertEqual(format_pair_code("000000"), "000-000")
        self.assertEqual(format_pair_code("ZZZZZZ"), "ZZZ-ZZZ")
        self.assertEqual(format_pair_code("A1B2C3"), "A1B-2C3")

    def test_includes_hyphen_at_position_3(self):
        raw = "123456"
        formatted = format_pair_code(raw)
        self.assertEqual(formatted[3], "-")

    def test_output_is_7_characters(self):
        raw = generate_pair_code()
        formatted = format_pair_code(raw)
        self.assertEqual(len(formatted), 7)


class TestValidatePairCode(unittest.TestCase):
    """Tests for validate_pair_code()."""

    def test_accepts_valid_formatted_code(self):
        self.assertTrue(validate_pair_code("ABC-123"))
        self.assertTrue(validate_pair_code("ZZZ-999"))
        self.assertTrue(validate_pair_code("A1B-2C3"))

    def test_rejects_missing_hyphen(self):
        self.assertFalse(validate_pair_code("ABC123"))

    def test_rejects_wrong_hyphen_position(self):
        self.assertFalse(validate_pair_code("AB-C123"))
        self.assertFalse(validate_pair_code("ABC1-23"))

    def test_rejects_lowercase_letters(self):
        self.assertFalse(validate_pair_code("abc-123"))

    def test_rejects_empty_string(self):
        self.assertFalse(validate_pair_code(""))

    def test_rejects_too_short(self):
        self.assertFalse(validate_pair_code("AB-123"))

    def test_rejects_too_long(self):
        self.assertFalse(validate_pair_code("ABCD-1234"))

    def test_rejects_special_characters(self):
        self.assertFalse(validate_pair_code("AB_-123"))
        self.assertFalse(validate_pair_code("AB$-123"))
        self.assertFalse(validate_pair_code("AB/-123"))

    def test_rejects_none(self):
        self.assertFalse(validate_pair_code(None))  # type: ignore


class TestIntegration(unittest.TestCase):
    """End-to-end flow: generate -> format -> validate."""

    def test_full_flow_roundtrip(self):
        for _ in range(100):
            raw = generate_pair_code()
            formatted = format_pair_code(raw)
            self.assertTrue(validate_pair_code(formatted))

    def test_formatted_accepts_raw_after_strip(self):
        raw = generate_pair_code()
        formatted = format_pair_code(raw)
        stripped = formatted.replace("-", "")
        self.assertEqual(stripped, raw)
        self.assertEqual(len(stripped), 6)


if __name__ == "__main__":
    unittest.main()
