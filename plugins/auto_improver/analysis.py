"""
Auto Improver — Analysis Engine
Handles conversation analysis, issue detection, and improvement suggestions.
"""

import json
import os
import threading
from collections import Counter
from datetime import datetime

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(PLUGIN_DIR, "results.json")
MESSAGES_CACHE_FILE = os.path.join(PLUGIN_DIR, "messages_cache.json")

_lock = threading.Lock()

# Default analysis rules (medium depth)
DEFAULT_RULES = {
    "max_response_length": 500,   # words
    "max_tool_calls_per_turn": 10,
    "min_response_length": 20,
    "repetition_threshold": 0.7,
    "check_tone": True,
    "check_structure": True,
    "check_tool_usage": True,
}

# Issue severity levels
SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"


def get_rules_for_depth(depth):
    """Return analysis rules adjusted for the given depth setting."""
    if depth == "shallow":
        return {**DEFAULT_RULES, "max_response_length": 1000, "min_response_length": 10, "max_tool_calls_per_turn": 15}
    elif depth == "deep":
        return {**DEFAULT_RULES, "max_response_length": 300, "min_response_length": 30, "max_tool_calls_per_turn": 5}
    return DEFAULT_RULES.copy()  # medium (default)


def load_results():
    """Load analysis results from file."""
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            return json.load(f)
    return {"analyses": [], "sessions": {}}


def save_results(data):
    """Save analysis results to file."""
    with open(RESULTS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_messages_cache():
    """Load per-session message cache from file."""
    if os.path.exists(MESSAGES_CACHE_FILE):
        with open(MESSAGES_CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_messages_cache(cache):
    """Save per-session message cache to file."""
    with open(MESSAGES_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2, default=str)


def count_words(text):
    """Count words in text."""
    if not text:
        return 0
    return len(text.split())


def detect_repetition(text, threshold=0.7):
    """Detect repetitive content in text."""
    if not text or len(text.split()) < 10:
        return False, 0.0

    sentences = [s.strip() for s in text.replace('\n', ' ').split('.') if len(s.strip()) > 10]
    if len(sentences) < 3:
        return False, 0.0

    # Limit to first 50 sentences to avoid O(n²) on very long texts
    sentences = sentences[:50]

    max_similarity = 0.0
    for i in range(len(sentences)):
        for j in range(i + 1, len(sentences)):
            similarity = calculate_similarity(sentences[i], sentences[j])
            if similarity >= threshold:
                return True, similarity  # Early exit once threshold is hit
            max_similarity = max(max_similarity, similarity)

    return False, max_similarity


def calculate_similarity(text1, text2):
    """Calculate similarity between two texts (simple word overlap)."""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union) if union else 0.0


def detect_long_response(text, rules=None):
    """Detect if response is too long."""
    rules = rules or DEFAULT_RULES
    word_count = count_words(text)
    if word_count > rules["max_response_length"]:
        return True, word_count
    return False, word_count


def detect_short_response(text, rules=None):
    """Detect if response is too short."""
    rules = rules or DEFAULT_RULES
    word_count = count_words(text)
    if word_count < rules["min_response_length"]:
        return True, word_count
    return False, word_count


def detect_inefficient_tool_usage(tool_calls, rules=None):
    """Detect inefficient tool usage patterns."""
    rules = rules or DEFAULT_RULES
    issues = []

    if not tool_calls:
        return issues

    # Check for excessive tool calls
    if len(tool_calls) > rules["max_tool_calls_per_turn"]:
        issues.append({
            "type": "excessive_tool_calls",
            "severity": SEVERITY_MEDIUM,
            "message": f"Too many tool calls in one turn: {len(tool_calls)} (max recommended: {rules['max_tool_calls_per_turn']})",
            "suggestion": "Consider combining multiple operations into a single tool call where possible."
        })

    # Check for redundant tool calls (same tool called more than twice)
    tool_names = [tc.get("name", "unknown") for tc in tool_calls]
    tool_counts = Counter(tool_names)
    for tool, count in tool_counts.items():
        if count > 2:
            issues.append({
                "type": "redundant_tool_calls",
                "severity": SEVERITY_LOW,
                "message": f"Tool '{tool}' called {count} times in one turn",
                "suggestion": f"Consider batching or caching results for '{tool}' calls."
            })

    return issues


def detect_missing_information(messages):
    """Detect if key information might be missing from conversation."""
    issues = []

    if not messages:
        return issues

    user_messages = [m for m in messages if m.get("role") == "user"]
    assistant_messages = [m for m in messages if m.get("role") == "assistant"]

    if user_messages and assistant_messages:
        avg_user_length = sum(count_words(m.get("content", "")) for m in user_messages) / len(user_messages)
        avg_assistant_length = sum(count_words(m.get("content", "")) for m in assistant_messages) / len(assistant_messages)

        if avg_assistant_length < 30 and avg_user_length > 50:
            issues.append({
                "type": "short_responses",
                "severity": SEVERITY_MEDIUM,
                "message": "Assistant responses are significantly shorter than user messages. Users may expect more detailed answers.",
                "suggestion": "Provide more comprehensive and detailed responses to match user expectations."
            })

    return issues


def analyze_tone(text):
    """Analyze tone of the response."""
    issues = []

    if not text:
        return issues

    text_lower = text.lower()

    formal_words = ["hereby", "aforementioned", "whilst", "furthermore", "notwithstanding"]
    formal_count = sum(1 for word in formal_words if word in text_lower)
    if formal_count > 3:
        issues.append({
            "type": "overly_formal",
            "severity": SEVERITY_LOW,
            "message": "Response uses overly formal language",
            "suggestion": "Use more conversational and approachable language."
        })

    negative_words = ["cannot", "won't", "don't", "impossible", "never", "fail"]
    negative_count = sum(1 for word in negative_words if word in text_lower)
    if negative_count > 5:
        issues.append({
            "type": "negative_tone",
            "severity": SEVERITY_MEDIUM,
            "message": "Response contains frequent negative language",
            "suggestion": "Try to frame responses positively where possible."
        })

    return issues


def analyze_structure(text):
    """Analyze structure of the response."""
    issues = []

    if not text:
        return issues

    has_headings = any(line.strip().startswith('#') for line in text.split('\n'))
    has_lists = any(line.strip().startswith(('-', '*', '1.', '•')) for line in text.split('\n'))
    has_paragraphs = text.count('\n\n') > 0

    if not has_headings and not has_lists and not has_paragraphs and count_words(text) > 100:
        issues.append({
            "type": "poor_structure",
            "severity": SEVERITY_MEDIUM,
            "message": "Long response lacks proper structure (headings, lists, or paragraphs)",
            "suggestion": "Use headings, bullet points, or paragraphs to improve readability."
        })

    return issues


def analyze_session(session_id, agent_id, messages, tool_calls=None, depth="medium"):
    """
    Main analysis function. Analyzes a session's conversation.

    Args:
        session_id: ID of the session
        agent_id: ID of the agent
        messages: List of message dicts with 'role' and 'content'
        tool_calls: Optional list of tool call dicts
        depth: Analysis depth — "shallow", "medium", or "deep"

    Returns:
        dict: Analysis results
    """
    if not messages:
        return {
            "session_id": session_id,
            "agent_id": agent_id,
            "timestamp": datetime.now().isoformat(),
            "issues": [],
            "suggestions": [],
            "score": 100,
            "summary": "No messages to analyze.",
            "message_count": 0,
            "word_count": 0,
        }

    rules = get_rules_for_depth(depth)
    issues = []
    suggestions = []

    assistant_messages = [m for m in messages if m.get("role") == "assistant"]
    all_assistant_text = " ".join(m.get("content", "") for m in assistant_messages)

    # 1. Check response length
    is_long, word_count = detect_long_response(all_assistant_text, rules)
    if is_long:
        issues.append({
            "type": "long_response",
            "severity": SEVERITY_MEDIUM,
            "message": f"Total response length is {word_count} words (max recommended: {rules['max_response_length']})",
            "suggestion": "Consider breaking long responses into multiple shorter turns or using summaries."
        })

    # 2. Check for short responses
    for msg in assistant_messages:
        content = msg.get("content", "")
        is_short, wc = detect_short_response(content, rules)
        if is_short and wc > 0:
            issues.append({
                "type": "short_response",
                "severity": SEVERITY_LOW,
                "message": f"Short response detected ({wc} words)",
                "suggestion": "Provide more detailed and helpful responses."
            })

    # 3. Check for repetition
    is_repetitive, similarity = detect_repetition(all_assistant_text, rules["repetition_threshold"])
    if is_repetitive:
        issues.append({
            "type": "repetitive_content",
            "severity": SEVERITY_MEDIUM,
            "message": f"Repetitive content detected (similarity: {similarity:.0%})",
            "suggestion": "Vary your language and avoid repeating the same points."
        })

    # 4. Check tool usage
    if tool_calls and rules["check_tool_usage"]:
        tool_issues = detect_inefficient_tool_usage(tool_calls, rules)
        issues.extend(tool_issues)

    # 5. Check for missing information
    info_issues = detect_missing_information(messages)
    issues.extend(info_issues)

    # 6. Check tone
    if rules["check_tone"]:
        tone_issues = analyze_tone(all_assistant_text)
        issues.extend(tone_issues)

    # 7. Check structure
    if rules["check_structure"]:
        structure_issues = analyze_structure(all_assistant_text)
        issues.extend(structure_issues)

    # Calculate score (100 = perfect, lower = more issues)
    severity_weights = {
        SEVERITY_LOW: 2,
        SEVERITY_MEDIUM: 5,
        SEVERITY_HIGH: 10,
        SEVERITY_CRITICAL: 20,
    }
    total_penalty = sum(severity_weights.get(issue.get("severity"), 5) for issue in issues)
    score = max(0, 100 - total_penalty)

    # Generate overall suggestions grouped by category
    if issues:
        suggestion_categories = {}
        for issue in issues:
            cat = issue["type"]
            if cat not in suggestion_categories:
                suggestion_categories[cat] = []
            suggestion_categories[cat].append(issue["suggestion"])

        suggestions = [
            {"category": cat, "suggestions": list(set(suggs))}
            for cat, suggs in suggestion_categories.items()
        ]

    summary_parts = [
        f"Analyzed {len(messages)} messages from agent '{agent_id}'.",
        f"Found {len(issues)} issue(s) with overall score: {score}/100.",
    ]
    high_severity = [i for i in issues if i.get("severity") in [SEVERITY_HIGH, SEVERITY_CRITICAL]]
    if high_severity:
        summary_parts.append(f"⚠️ {len(high_severity)} high/critical issue(s) need immediate attention.")
    summary = " ".join(summary_parts)

    return {
        "session_id": session_id,
        "agent_id": agent_id,
        "timestamp": datetime.now().isoformat(),
        "issues": issues,
        "suggestions": suggestions,
        "score": score,
        "summary": summary,
        "message_count": len(messages),
        "word_count": word_count,
    }


def save_analysis_result(result):
    """Save analysis result to results.json; cache messages separately."""
    # Extract messages before saving — stored separately to avoid data bloat
    messages = result.pop("stored_messages", None)

    with _lock:
        data = load_results()

        data["analyses"].append(result)

        # Update sessions index
        session_id = result["session_id"]
        data["sessions"][session_id] = {
            "agent_id": result["agent_id"],
            "last_analysis": result["timestamp"],
            "score": result["score"],
            "issue_count": len(result["issues"]),
        }

        # Prune analyses to last 100
        if len(data["analyses"]) > 100:
            data["analyses"] = data["analyses"][-100:]

        # Prune sessions to only those still in analyses
        active_sessions = {a["session_id"] for a in data["analyses"]}
        data["sessions"] = {k: v for k, v in data["sessions"].items() if k in active_sessions}

        save_results(data)

        # Save messages to separate cache, pruned to active sessions
        if messages:
            cache = load_messages_cache()
            cache[session_id] = messages
            cache = {k: v for k, v in cache.items() if k in active_sessions}
            save_messages_cache(cache)

    return result


def get_recent_analyses(limit=10):
    """Get recent analysis results."""
    data = load_results()
    analyses = data.get("analyses", [])
    return analyses[-limit:] if analyses else []


def get_session_analysis(session_id):
    """Get all analyses for a specific session."""
    data = load_results()
    return [a for a in data.get("analyses", []) if a.get("session_id") == session_id]


def get_agent_performance(agent_id):
    """Get performance summary for an agent."""
    data = load_results()
    agent_analyses = [a for a in data.get("analyses", []) if a.get("agent_id") == agent_id]

    if not agent_analyses:
        return {
            "agent_id": agent_id,
            "total_analyses": 0,
            "avg_score": 0,
            "total_issues": 0,
            "recent_scores": [],
        }

    scores = [a.get("score", 0) for a in agent_analyses]
    total_issues = sum(len(a.get("issues", [])) for a in agent_analyses)

    return {
        "agent_id": agent_id,
        "total_analyses": len(agent_analyses),
        "avg_score": sum(scores) / len(scores) if scores else 0,
        "total_issues": total_issues,
        "recent_scores": scores[-10:],
    }
