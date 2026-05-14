"""Unit tests for GitHub webhook filter functions (_resolve_field, _evaluate_filters)."""

import json
import sys
import types
from unittest.mock import patch

# Import the functions directly from the routes module
sys.path.insert(0, sys.path[0])  # ensure project root is first


class TestResolveField:
    """Tests for _resolve_field(data, field_path)."""

    def setup_method(self):
        # Import after sys.path is set; stub out _log to avoid DB/plugin_manager
        import plugins.github_webhook.routes as routes
        routes._log = lambda level, msg: None  # suppress logging
        self.resolve = routes._resolve_field

    def test_simple_key(self):
        assert self.resolve({"action": "opened"}, "action") == "opened"

    def test_nested_dot_notation(self):
        data = {"pull_request": {"state": "open"}}
        assert self.resolve(data, "pull_request.state") == "open"

    def test_deeply_nested(self):
        data = {"repository": {"full_name": "org/repo"}}
        assert self.resolve(data, "repository.full_name") == "org/repo"

    def test_missing_key_returns_none(self):
        assert self.resolve({"action": "opened"}, "missing") is None

    def test_missing_nested_key_returns_none(self):
        data = {"pull_request": {"title": "fix"}}
        assert self.resolve(data, "pull_request.state") is None

    def test_empty_path_returns_none(self):
        data = {"action": "opened"}
        # Empty string splits to [""], "" not in data -> None
        assert self.resolve(data, "") is None

    def test_numeric_value(self):
        data = {"number": 42}
        assert self.resolve(data, "number") == 42

    def test_boolean_value(self):
        data = {"prerelease": True}
        assert self.resolve(data, "prerelease") is True


class TestEvaluateFilters:
    """Tests for _evaluate_filters(filters_json_str, data)."""

    def setup_method(self):
        import plugins.github_webhook.routes as routes
        routes._log = lambda level, msg: None  # suppress logging
        self.evaluate = routes._evaluate_filters

    def test_empty_string_returns_true(self):
        assert self.evaluate("", {"action": "opened"}) is True

    def test_none_returns_true(self):
        assert self.evaluate(None, {"action": "opened"}) is True

    def test_empty_array_returns_true(self):
        assert self.evaluate("[]", {"action": "opened"}) is True

    def test_equals_match_pass(self):
        filters = '[{"field": "action", "match": "equals", "value": "opened"}]'
        assert self.evaluate(filters, {"action": "opened"}) is True

    def test_equals_match_fail(self):
        filters = '[{"field": "action", "match": "equals", "value": "opened"}]'
        assert self.evaluate(filters, {"action": "closed"}) is False

    def test_nested_field_equals(self):
        filters = '[{"field": "pull_request.state", "match": "equals", "value": "open"}]'
        data = {"pull_request": {"state": "open"}}
        assert self.evaluate(filters, data) is True

    def test_regex_match_pass(self):
        filters = '[{"field": "ref", "match": "regex", "value": "^refs/heads/main$"}]'
        assert self.evaluate(filters, {"ref": "refs/heads/main"}) is True

    def test_regex_match_fail(self):
        filters = '[{"field": "ref", "match": "regex", "value": "^refs/heads/main$"}]'
        assert self.evaluate(filters, {"ref": "refs/heads/dev"}) is False

    def test_multiple_filters_and_logic_all_pass(self):
        filters = json.dumps([
            {"field": "action", "match": "equals", "value": "opened"},
            {"field": "repository.full_name", "match": "regex", "value": "^my-org/"},
        ])
        data = {
            "action": "opened",
            "repository": {"full_name": "my-org/my-repo"},
        }
        assert self.evaluate(filters, data) is True

    def test_multiple_filters_and_logic_one_fails(self):
        filters = json.dumps([
            {"field": "action", "match": "equals", "value": "opened"},
            {"field": "repository.full_name", "match": "regex", "value": "^my-org/"},
        ])
        data = {
            "action": "opened",
            "repository": {"full_name": "other-org/my-repo"},
        }
        assert self.evaluate(filters, data) is False

    def test_malformed_json_returns_true(self):
        assert self.evaluate("not json", {"action": "opened"}) is True
        assert self.evaluate("{invalid", {"action": "opened"}) is True

    def test_invalid_regex_returns_true(self):
        filters = '[{"field": "ref", "match": "regex", "value": "[invalid"}]'
        assert self.evaluate(filters, {"ref": "refs/heads/main"}) is True

    def test_unknown_match_type_returns_true(self):
        filters = '[{"field": "action", "match": "contains", "value": "open"}]'
        assert self.evaluate(filters, {"action": "opened"}) is True

    def test_filter_entry_not_object_returns_true(self):
        filters = '["not an object"]'
        assert self.evaluate(filters, {"action": "opened"}) is True

    def test_missing_field_in_payload(self):
        filters = '[{"field": "pull_request.state", "match": "equals", "value": "open"}]'
        # payload has no pull_request key
        assert self.evaluate(filters, {"action": "opened"}) is False

    def test_value_type_coercion(self):
        # value in filter is string "true", resolved value is boolean True -> str(True) = "True"
        filters = '[{"field": "prerelease", "match": "equals", "value": "True"}]'
        assert self.evaluate(filters, {"prerelease": True}) is True
