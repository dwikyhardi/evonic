# Normalize quote-like characters in text before sending to LLM servers.
#
# llama.cpp --jinja parses tool call arguments as JSON server-side. When the
# LLM echoes straight apostrophes or double quotes verbatim inside a JSON
# string value, the parser fails with a 500 "missing closing quote" error.
# Replacing them with semantically equivalent typographic characters prevents
# the model from reproducing them in tool call output.

_QUOTE_TABLE = str.maketrans({
    "\u0027": "\u2019",  # ' straight apostrophe         → ' right single quotation mark
    "\u2018": "\u2019",  # ' left single quotation mark  → ' right single quotation mark
    "\u201b": "\u2019",  # ‛ reversed single quot. mark  → ' right single quotation mark
    "\u0022": "\u201c",  # " straight double quote        → " left double quotation mark
    "\u201e": "\u201c",  # „ low double quotation mark    → " left double quotation mark
})


def normalize_llm_text(text: str) -> str:
    """Replace JSON-unsafe quote characters with safe typographic equivalents."""
    return text.translate(_QUOTE_TABLE) if text else text
