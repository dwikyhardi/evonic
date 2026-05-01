# CoT Tool Call Fallback

## Problem

Local models (especially Qwen-based) sometimes emit `<tool_call>` XML inside their thinking/reasoning content instead of in the main response body. When this happens the agent loop sees no tool calls and treats the turn as a final answer, silently breaking the tool loop.

Example of the problematic output:

```
<think>
Oke, aku udah baca semua file yang relevan. Sekarang aku paham situasinya.

Tapi masalahnya, aku perlu cek apakah ada issue lain. Aku cek juga file berikutnya.

<tool_call>
<function=read_file>
<parameter=file_path>
/workspace/skills/kanban_agent/backend/tools/kanban_add_comment.py
</parameter>
</function>
</tool_call>
</think>
```

## Two Failure Scenarios

### 1. `reasoning_content` field (llama.cpp `--reasoning` mode)
The model returns a separate `reasoning_content` field alongside the main `content`. If the model places tool calls inside this reasoning field, the existing Qwen fallback check (which only scans `raw_content`) misses them entirely.

### 2. `<think>` tags inside `raw_content`
The model wraps all reasoning — including tool calls — inside `<think>...</think>` in the main content. The existing Qwen check at `agent_runtime.py:754` does a string search on `raw_content` and will usually catch these, but after thinking extraction the `content` variable may end up empty or malformed. The new fallback provides a reliable second chance.

## Solution

A fallback check was added to `backend/agent_runtime.py` immediately after thinking extraction. It runs only when no `tool_calls` have been found by the earlier checks, inspects the extracted thinking text, and recovers any `<tool_call>` XML found there.

```python
# Fallback: recover tool calls from thinking/CoT content.
if not tool_calls:
    cot_text = reasoning_text or thinking
    if cot_text and '<tool_call>' in cot_text:
        from evaluator.qwen_parser import extract_qwen_tool_calls, qwen_tool_calls_to_openai_format
        cot_calls = extract_qwen_tool_calls(cot_text)
        if cot_calls:
            tool_calls = qwen_tool_calls_to_openai_format(cot_calls)
            print(f"[AgentRuntime] Recovered {len(tool_calls)} tool call(s) from thinking/CoT content")
```

### Key design decisions

- **Reuses existing parsers**: `extract_qwen_tool_calls` and `qwen_tool_calls_to_openai_format` from `evaluator/qwen_parser.py`.
- **No interference with normal paths**: the guard `if not tool_calls` ensures the fallback is skipped when structured tool calls were already found.
- **`thinking` initialized to `None`**: added before the if/elif/else thinking-extraction block so the variable is always in scope regardless of which branch executes.
- **Tool call XML is not stripped from thinking text**: it is cosmetic and seeing raw tool calls in the timeline aids debugging.
- **Diagnosable via logs**: the `[AgentRuntime] Recovered N tool call(s)` print line makes the fallback visible in server output.

## Relevant Files

| File | Role |
|------|------|
| `backend/agent_runtime.py` | Fallback added after thinking extraction in `_run_tool_loop` |
| `evaluator/qwen_parser.py` | `extract_qwen_tool_calls`, `qwen_tool_calls_to_openai_format` — reused by the fallback |
| `train/evaluator/llm_client.py` | `strip_thinking_tags` — extracts thinking from `<think>` tags |

## Tests

Two test locations cover this feature:

### `unit_tests/test_qwen_parser.py`
Parser-level tests verifying that `extract_qwen_tool_calls` can handle tool calls embedded in `<think>` tags and plain CoT prose:
- `test_extract_from_think_wrapped_content`
- `test_extract_from_cot_prose`
- `test_openai_format_from_cot_tool_call`
- `test_extract_multiple_from_cot`
- `test_no_false_positive_from_pure_reasoning`

### `unit_tests/test_cot_tool_call_fallback.py`
Integration-level tests that replicate the exact fallback code path from `agent_runtime.py`:
- **Scenario 1** (`reasoning_content` field): `test_reasoning_content_field_*`
- **Scenario 2** (`<think>` tags in `raw_content`): `test_think_tag_*`
- **Scenario 3** (multiple tool calls in CoT): `test_multiple_tool_calls_*`
- **Regressions**: no false positive, structured tool_calls not overridden, empty response no crash

Run with:
```bash
pytest unit_tests/test_qwen_parser.py unit_tests/test_cot_tool_call_fallback.py -v
```
