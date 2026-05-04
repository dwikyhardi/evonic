"""Tests for backend.channels.pairing — Pairing Code Generator (XXXXXX)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.channels.pairing import generate_pair_code, format_pair_code, validate_pair_code


class TestGeneratePairCode(unittest.TestCase):
    """Tests for generate_pair_code()."""

    # Unambiguous charset: no 0, O, 1, I, L
    VALID_CHARS = set('ABCDEFGHJKMNPQRSTUVWXYZ23456789')
    AMBIGUOUS_CHARS = set('01OIL')

    def test_returns_6_characters(self):
        code = generate_pair_code()
        self.assertEqual(len(code), 6)

    def test_contains_only_unambiguous_chars(self):
        for _ in range(200):
            code = generate_pair_code()
            for ch in code:
                self.assertIn(ch, self.VALID_CHARS)

    def test_never_contains_ambiguous_chars(self):
        for _ in range(200):
            code = generate_pair_code()
            for ch in code:
                self.assertNotIn(ch, self.AMBIGUOUS_CHARS)

    def test_no_two_codes_are_identical_in_500_runs(self):
        codes = {generate_pair_code() for _ in range(500)}
        self.assertEqual(len(codes), 500)

    def test_consecutive_codes_do_not_collide_frequently(self):
        for _ in range(5):
            codes = {generate_pair_code() for _ in range(100)}
            self.assertEqual(len(codes), 100)


class TestFormatPairCode(unittest.TestCase):
    """Tests for format_pair_code() — returns code as-is (no hyphen)."""

    def test_returns_same_uppercase(self):
        self.assertEqual(format_pair_code("ABC123"), "ABC123")

    def test_uppercases_input(self):
        self.assertEqual(format_pair_code("abc123"), "ABC123")

    def test_output_is_6_characters(self):
        raw = generate_pair_code()
        self.assertEqual(len(format_pair_code(raw)), 6)

    def test_no_hyphen_in_output(self):
        raw = generate_pair_code()
        self.assertNotIn('-', format_pair_code(raw))


class TestValidatePairCode(unittest.TestCase):
    """Tests for validate_pair_code()."""

    def test_accepts_valid_6char_code(self):
        self.assertTrue(validate_pair_code("ABC123"))
        self.assertTrue(validate_pair_code("ZZZ999"))
        self.assertTrue(validate_pair_code("A1B2C3"))

    def test_rejects_hyphenated_code(self):
        self.assertFalse(validate_pair_code("ABC-123"))

    def test_rejects_lowercase_letters(self):
        self.assertFalse(validate_pair_code("abc123"))

    def test_rejects_empty_string(self):
        self.assertFalse(validate_pair_code(""))

    def test_rejects_too_short(self):
        self.assertFalse(validate_pair_code("AB123"))

    def test_rejects_too_long(self):
        self.assertFalse(validate_pair_code("ABCD1234"))

    def test_rejects_special_characters(self):
        self.assertFalse(validate_pair_code("AB_123"))
        self.assertFalse(validate_pair_code("AB$123"))

    def test_rejects_none(self):
        self.assertFalse(validate_pair_code(None))  # type: ignore


class TestIntegration(unittest.TestCase):
    """End-to-end flow: generate -> format -> validate."""

    def test_full_flow_roundtrip(self):
        for _ in range(100):
            raw = generate_pair_code()
            formatted = format_pair_code(raw)
            self.assertTrue(validate_pair_code(formatted))

    def test_format_is_identity(self):
        raw = generate_pair_code()
        self.assertEqual(format_pair_code(raw), raw)


if __name__ == "__main__":
    unittest.main()
