/* chat-ui.js — shared chat rendering component for Evonic */

/* ==================== Global Utilities ==================== */

function chatEscapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text == null ? '' : text);
    return div.innerHTML;
}

function chatTruncateLine(text, max) {
    const first = (text || '').split('\n')[0].trim();
    return first.length > max ? first.slice(0, max) + '\u2026' : first;
}

/* ==================== Lightweight Python Syntax Highlighter ==================== */

function highlightPython(code) {
    if (!code) return '';

    // Token patterns run on RAW code to avoid breaking HTML entities like &amp;
    const patterns = [
        // f-strings (must come before regular strings)
        { type: 'fstring', regex: /f"(?:[^"\\]|\\.)*"/g },
        { type: 'fstring', regex: /f'(?:[^'\\]|\\.)*'/g },
        { type: 'fstring', regex: /f"""(?:[^"]|\\.)*"""/g },
        { type: 'fstring', regex: /f'''(?:[^']|\\.)*'''/g },
        // Triple-quoted strings
        { type: 'string', regex: /"""(?:[^"]|\\.)*"""/g },
        { type: 'string', regex: /'''(?:[^']|\\.)*'''/g },
        // Regular strings
        { type: 'string', regex: /"(?:[^"\\]|\\.)*"/g },
        { type: 'string', regex: /'(?:[^'\\]|\\.)*'/g },
        // Comments
        { type: 'comment', regex: /#.*$/gm },
        // Decorators
        { type: 'decorator', regex: /@\w+(?:\.\w+)*/g },
        // Built-in functions (must come before general function pattern)
        { type: 'builtin', regex: /\b(print|len|range|list|dict|str|int|float|type|isinstance|enumerate|zip|map|filter|sorted|reversed|open|input|super|set|tuple|abs|max|min|sum|round|any|all|hasattr|getattr|setattr|delattr|callable|repr|format|hash|id|dir|vars|help|slice|staticmethod|classmethod|property|issubclass|iter|next|bin|oct|hex|chr|ord|pow|divmod|compile|eval|exec|globals|locals|breakpoint|memoryview|frozenset|complex|ascii)\b/g },
        // Keywords
        { type: 'keyword', regex: /\b(def|class|if|elif|else|for|while|return|import|from|as|try|except|finally|with|raise|pass|break|continue|lambda|yield|assert|del|global|nonlocal|async|await)\b/g },
        // Boolean / None
        { type: 'boolean', regex: /\b(True|False)\b/g },
        { type: 'none', regex: /\bNone\b/g },
        // self / cls
        { type: 'self', regex: /\b(self|cls)\b/g },
        // Numbers
        { type: 'number', regex: /\b(?:0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)\b/g },
        // Function calls
        { type: 'function', regex: /\b([a-zA-Z_]\w*)\s*(?=\()/g },
        // Operators
        { type: 'operator', regex: /(?:==|!=|<=|>=|<<|>>|\*\*|\/\/|&&|\|\||[+\-*/%=<>!&|^~])/g },
    ];

    // Collect all matches on the raw code
    const matches = [];
    for (const p of patterns) {
        let m;
        const re = new RegExp(p.regex.source, p.regex.flags);
        while ((m = re.exec(code)) !== null) {
            matches.push({
                type: p.type,
                start: m.index,
                end: m.index + m[0].length,
                text: m[0],
            });
            if (m[0].length === 0) re.lastIndex++;
        }
    }

    // Sort by start position, then by length descending (longer match wins)
    matches.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));

    // Remove overlapping matches (keep first/longest)
    const filtered = [];
    let lastEnd = -1;
    for (const m of matches) {
        if (m.start >= lastEnd) {
            filtered.push(m);
            lastEnd = m.end;
        }
    }

    // Build result: escape each raw segment to preserve HTML entities correctly
    let result = '';
    let pos = 0;
    for (const m of filtered) {
        if (m.start > pos) {
            result += chatEscapeHtml(code.slice(pos, m.start));
        }
        result += '<span class="hl-' + m.type + '">' + chatEscapeHtml(m.text) + '</span>';
        pos = m.end;
    }
    if (pos < code.length) {
        result += chatEscapeHtml(code.slice(pos));
    }

    return result;
}

/* ==================== Lightweight Diff Syntax Highlighter ==================== */

function highlightDiff(patch) {
    if (!patch) return '';
    let escaped = chatEscapeHtml(patch);
    let lines = escaped.split('\n');
    let html = '';

    for (let line of lines) {
        if (line.startsWith('@@')) {
            // Hunk header
            html += '<span class="hl-diff-header">' + line + '</span>\n';
        } else if (line.startsWith('--- ') || line.startsWith('+++ ')) {
            // File header
            html += '<span class="hl-diff-filename">' + line + '</span>\n';
        } else if (line.startsWith('+')) {
            // Addition
            html += '<span class="hl-diff-add">' + line + '</span>\n';
        } else if (line.startsWith('-')) {
            // Removal
            html += '<span class="hl-diff-remove">' + line + '</span>\n';
        } else if (line.startsWith('\\')) {
            // No newline marker
            html += '<span class="hl-diff-meta">' + line + '</span>\n';
        } else {
            // Context
            html += '<span class="hl-diff-context">' + line + '</span>\n';
        }
    }

    return html;
}

/* ==================== renderTimelineEntry ==================== */

/* ==================== Tool Param Rendering ==================== */

function resolveParamView(paramName, paramTypes) {
    // Explicit view from tool definition takes precedence
    if (paramTypes && paramTypes[paramName]) return paramTypes[paramName];
    return null; // default: key-value inline
}

function renderCodeBlock(value) {
    return `<pre class="runpy-code-block mt-0.5">${highlightPython(String(value))}</pre>`;
}

function renderDiffBlock(value) {
    return `<pre class="diff-code-block mt-0.5">${highlightDiff(String(value))}</pre>`;
}

/* ==================== Str-Replace Visual Diff ==================== */

function computeLineDiff(oldLines, newLines) {
    const m = oldLines.length, n = newLines.length;
    // Guard against huge inputs to avoid perf issues
    if (m * n > 60000) {
        return [
            ...oldLines.map(l => ({ type: 'remove', line: l })),
            ...newLines.map(l => ({ type: 'add', line: l }))
        ];
    }
    // LCS DP
    const dp = Array.from({ length: m + 1 }, () => new Int32Array(n + 1));
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            if (oldLines[i - 1] === newLines[j - 1]) dp[i][j] = dp[i - 1][j - 1] + 1;
            else dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
        }
    }
    // Backtrack
    const ops = [];
    let i = m, j = n;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
            ops.push({ type: 'context', line: oldLines[i - 1] });
            i--; j--;
        } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
            ops.push({ type: 'add', line: newLines[j - 1] });
            j--;
        } else {
            ops.push({ type: 'remove', line: oldLines[i - 1] });
            i--;
        }
    }
    return ops.reverse();
}

function renderStrReplaceDiff(oldStr, newStr, filePath) {
    const oldLines = String(oldStr).split('\n');
    const newLines = String(newStr).split('\n');
    const ops = computeLineDiff(oldLines, newLines);

    const changed = ops.map((op, i) => op.type !== 'context' ? i : -1).filter(i => i !== -1);
    if (changed.length === 0) {
        return `<div class="text-xs text-gray-400 italic mt-1">No changes detected</div>`;
    }

    // Build hunks with 3-line context
    const CTX = 3;
    const hunks = [];
    let hs = -1, he = -1;
    for (const idx of changed) {
        const lo = Math.max(0, idx - CTX), hi = Math.min(ops.length - 1, idx + CTX);
        if (hs === -1 || lo > he + 1) {
            if (hs !== -1) hunks.push([hs, he]);
            hs = lo; he = hi;
        } else {
            he = Math.max(he, hi);
        }
    }
    if (hs !== -1) hunks.push([hs, he]);

    let html = '';
    if (filePath) {
        html += `<span class="hl-diff-filename">--- ${chatEscapeHtml(String(filePath))}</span>\n`;
        html += `<span class="hl-diff-filename">+++ ${chatEscapeHtml(String(filePath))}</span>\n`;
    }

    for (const [lo, hi] of hunks) {
        let oldLineNum = 1, newLineNum = 1;
        for (let k = 0; k < lo; k++) {
            if (ops[k].type !== 'add') oldLineNum++;
            if (ops[k].type !== 'remove') newLineNum++;
        }
        let oldCount = 0, newCount = 0;
        for (let k = lo; k <= hi; k++) {
            if (ops[k].type !== 'add') oldCount++;
            if (ops[k].type !== 'remove') newCount++;
        }
        html += `<span class="hl-diff-header">@@ -${oldLineNum},${oldCount} +${newLineNum},${newCount} @@</span>\n`;
        for (let k = lo; k <= hi; k++) {
            const { type, line } = ops[k];
            const esc = chatEscapeHtml(line);
            if (type === 'add')     html += `<span class="hl-diff-add">+${esc}</span>\n`;
            else if (type === 'remove') html += `<span class="hl-diff-remove">-${esc}</span>\n`;
            else                    html += `<span class="hl-diff-context"> ${esc}</span>\n`;
        }
    }

    return `<pre class="diff-code-block mt-0.5" style="max-height:400px;overflow-y:auto">${html}</pre>`;
}

function renderPlainTextBlock(value) {
    return `<pre class="text-xs bg-gray-50 dark:bg-gray-900 dark:text-gray-300 border border-gray-200 rounded p-2 overflow-x-auto font-mono text-gray-700 max-h-[300px] whitespace-pre-wrap">${chatEscapeHtml(String(value))}</pre>`;
}

function renderParamTable(params) {
    if (Object.keys(params).length === 0) return '';
    let rows = '';
    for (const [k, v] of Object.entries(params)) {
        const display = v === null || v === undefined ? '' : (typeof v === 'object' ? JSON.stringify(v) : String(v));
        rows += `<div class="contents">
            <span class="text-blue-400 font-semibold truncate">${chatEscapeHtml(k)}</span>
            <span class="text-blue-600 break-all">${chatEscapeHtml(display)}</span>
        </div>`;
    }
    return `<div class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs mt-1">${rows}</div>`;
}

function renderToolCallDetail(tool, args, paramTypes) {
    const pt = paramTypes || {};

    // Visual diff for str_replace-style tools (old_string + new_string)
    const oldKey = Object.prototype.hasOwnProperty.call(args, 'old_string') ? 'old_string'
                 : Object.prototype.hasOwnProperty.call(args, 'old_str')    ? 'old_str' : null;
    const newKey = Object.prototype.hasOwnProperty.call(args, 'new_string') ? 'new_string'
                 : Object.prototype.hasOwnProperty.call(args, 'new_str')    ? 'new_str' : null;
    if (oldKey && newKey) {
        const filePath = args.file_path || args.path || null;
        const meta = {};
        for (const [k, v] of Object.entries(args)) {
            if (k !== oldKey && k !== newKey) meta[k] = v;
        }
        let html = Object.keys(meta).length > 0 ? renderParamTable(meta) : '';
        html += `<div class="text-[10px] uppercase tracking-wide text-green-500 font-semibold mt-1.5">changes</div>`;
        html += renderStrReplaceDiff(args[oldKey], args[newKey], filePath);
        return html;
    }

    let html = ``;
    const inlineParams = {};
    const blockParams = [];

    for (const [key, value] of Object.entries(args)) {
        const view = resolveParamView(key, pt);
        if (view) {
            blockParams.push({key, value, view});
        } else {
            inlineParams[key] = value;
        }
    }

    if (Object.keys(inlineParams).length > 0) {
        html += renderParamTable(inlineParams);
    }

    for (const {key, value, view} of blockParams) {
        html += `<div class="text-[10px] uppercase tracking-wide text-blue-400 font-semibold mt-1.5">${chatEscapeHtml(key)}</div>`;
        if (view === 'code') html += renderCodeBlock(value);
        else if (view === 'diff') html += renderDiffBlock(value);
        else if (view === 'plain-text') html += renderPlainTextBlock(value);
    }

    return html;
}

function summarizeToolResult(result) {
    if (result === null || result === undefined) return 'OK';
    if (Array.isArray(result)) return `${result.length} item${result.length !== 1 ? 's' : ''}`;
    if (typeof result === 'object') {
        const keys = Object.keys(result);
        if (keys.length === 0) return 'OK';
        if ('status' in result) {
            const s = String(result.status);
            if ('message' in result && String(result.message).length < 100) return `${s}: ${String(result.message)}`;
            return s;
        }
        if ('message' in result && keys.length === 1) return String(result.message).slice(0, 120);
        if ('count' in result && typeof result.count === 'number') return `${result.count} item${result.count !== 1 ? 's' : ''}`;
        if ('total' in result && typeof result.total === 'number') return `${result.total} total`;
        if (keys.length === 1 && Array.isArray(result[keys[0]])) {
            const arr = result[keys[0]];
            return `${arr.length} ${keys[0]}`;
        }
        const parts = [];
        for (const k of keys.slice(0, 3)) {
            const v = result[k];
            if (v !== null && v !== undefined && typeof v !== 'object') parts.push(`${k}: ${String(v)}`);
        }
        if (parts.length > 0) return parts.join(' · ');
        return `${keys.length} field${keys.length !== 1 ? 's' : ''}`;
    }
    const s = String(result);
    return s.length > 120 ? s.slice(0, 117) + '...' : s;
}

function renderToolResultDetail(ev) {
    // Error: show message only, no raw JSON
    if (ev.error) {
        let msg = typeof ev.error === 'string' && ev.error.length > 1 ? ev.error : null;
        if (!msg && typeof ev.result === 'string') msg = ev.result;
        if (!msg && ev.result && typeof ev.result === 'object') msg = ev.result.error || ev.result.message || null;
        if (!msg) msg = 'Tool error';
        return `<div class="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1 font-mono whitespace-pre-wrap">${chatEscapeHtml(msg)}</div>`;
    }
    if (ev.tool === 'runpy' && typeof ev.result === 'object' && !ev.error && ev.result.exit_code !== undefined) {
        const r = ev.result;
        const hasStdout = r.stdout && r.stdout.trim().length > 0;
        const hasStderr = r.stderr && r.stderr.trim().length > 0;
        const hasError = r.exit_code !== 0;
        const statusColor = hasError ? 'text-red-600' : 'text-green-600';
        const statusBg = hasError ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200';
        const statusIcon = hasError ? '&#10060;' : '&#9989;';
        let panels = `<div class="flex items-center gap-2 mb-1.5 text-[10px] font-mono ${statusColor} ${statusBg} border rounded px-2 py-1">`;
        panels += `<span>${statusIcon} exit: ${chatEscapeHtml(String(r.exit_code))}</span>`;
        panels += `<span class="text-gray-400">|</span>`;
        panels += `<span>time: ${chatEscapeHtml(String(r.execution_time))}s</span>`;
        if (r.available_helpers) {
            panels += `<span class="text-gray-400">|</span><span class="text-gray-500">${Object.keys(r.available_helpers).length} helpers</span>`;
        }
        panels += `</div>`;
        if (hasStdout) {
            panels += `<div class="text-[10px] font-semibold text-gray-500 mb-0.5">stdout</div>`;
            panels += `<pre class="text-xs bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto font-mono text-gray-800 max-h-[200px]">${chatEscapeHtml(r.stdout)}</pre>`;
        }
        if (hasStderr) {
            panels += `<div class="text-[10px] font-semibold text-red-500 mb-0.5 mt-1">stderr</div>`;
            panels += `<pre class="text-xs bg-red-50 border border-red-200 rounded p-2 overflow-x-auto font-mono text-red-700 max-h-[200px]">${chatEscapeHtml(r.stderr)}</pre>`;
        }
        if (!hasStdout && !hasStderr) {
            panels += `<div class="text-xs text-gray-400 italic">No output</div>`;
        }
        return panels;
    }
    // Bash tool: treat stdout as plain text, show stderr separately
    if ((ev.tool === 'bash' || (!ev.tool && ev.result && ev.result.exit_code !== undefined)) && typeof ev.result === 'object' && !ev.error && ev.result.exit_code !== undefined) {
        const r = ev.result;
        let stdout = r.stdout;
        let stderr = r.stderr;
        // For truncated results: stdout/stderr are wrapped inside data as JSON string
        if (r.data && !stdout && !stderr) {
            try {
                const parsed = JSON.parse(r.data);
                stdout = parsed.stdout || '';
                stderr = parsed.stderr || '';
            } catch(e) { /* not JSON, fall through to raw data display */ }
        }
        const hasStdout = stdout && stdout.trim().length > 0;
        const hasStderr = stderr && stderr.trim().length > 0;
        const hasError = r.exit_code !== 0;
        const statusColor = hasError ? 'text-red-600' : 'text-green-600';
        const statusBg = hasError ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200';
        const statusIcon = hasError ? '&#10060;' : '&#9989;';
        let panels = `<div class="flex items-center gap-2 mb-1.5 text-[10px] font-mono ${statusColor} ${statusBg} border rounded px-2 py-1">`;
        panels += `<span>${statusIcon} exit: ${chatEscapeHtml(String(r.exit_code))}</span>`;
        panels += `<span class="text-gray-400">|</span>`;
        panels += `<span>time: ${chatEscapeHtml(String(r.execution_time))}s</span>`;
        panels += `</div>`;
        if (hasStdout) {
            panels += `<div class="text-[10px] font-semibold text-gray-500 mb-0.5">stdout</div>`;
            panels += `<pre class="text-xs border rounded p-2 overflow-x-auto font-mono max-h-[200px] whitespace-pre-wrap" style="background-color:#0a0b0c;color:#c8d0d8;border-color:#1a1b1c">${chatEscapeHtml(stdout)}</pre>`;
        }
        if (hasStderr) {
            panels += `<div class="text-[10px] font-semibold text-red-500 mb-0.5 mt-1">stderr</div>`;
            panels += `<pre class="text-xs bg-red-50 border border-red-200 rounded p-2 overflow-x-auto font-mono text-red-700 max-h-[200px] mt-1 whitespace-pre-wrap">${chatEscapeHtml(stderr)}</pre>`;
        }
        if (!hasStdout && !hasStderr) {
            if (r.data && String(r.data).trim().length > 0) {
                // Truncated result — stdout/stderr collapsed into data field by backend.
                // Try regex extraction if JSON parse failed above.
                if (!stdout && !stderr) {
                    const stdoutMatch = String(r.data).match(/"stdout"\s*:\s*"((?:[^"\\]|\\.)*)"/);
                    const stderrMatch = String(r.data).match(/"stderr"\s*:\s*"((?:[^"\\]|\\.)*)"/);
                    if (stdoutMatch && stdoutMatch[1]) {
                        try { stdout = JSON.parse('"' + stdoutMatch[1] + '"'); } catch(e) { stdout = stdoutMatch[1]; }
                    }
                    if (stderrMatch && stderrMatch[1]) {
                        try { stderr = JSON.parse('"' + stderrMatch[1] + '"'); } catch(e) { stderr = stderrMatch[1]; }
                    }
                    if (stdout || stderr) {
                        let out = '';
                        if (stdout && stdout.trim().length > 0) out += stdout;
                        if (stderr && stderr.trim().length > 0) {
                            if (out) out += '\n';
                            out += '[stderr]\n' + stderr;
                        }
                        panels += `<pre class="text-xs border rounded p-2 overflow-x-auto font-mono max-h-[200px] whitespace-pre-wrap" style="background-color:#0a0b0c;color:#c8d0d8;border-color:#1a1b1c">${chatEscapeHtml(out)}</pre>`;
                    } else {
                        panels += `<pre class="text-xs border rounded p-2 overflow-x-auto font-mono max-h-[200px] whitespace-pre-wrap" style="background-color:#0a0b0c;color:#c8d0d8;border-color:#1a1b1c">${chatEscapeHtml(String(r.data))}</pre>`;
                    }
                } else {
                    panels += `<pre class="text-xs border rounded p-2 overflow-x-auto font-mono max-h-[200px] whitespace-pre-wrap" style="background-color:#0a0b0c;color:#c8d0d8;border-color:#1a1b1c">${chatEscapeHtml(String(r.data))}</pre>`;
                }
            } else {
                panels += `<div class="text-xs text-gray-400 italic">No output</div>`;
            }
        }
        return panels;
    }
    // If the result is a plain string (e.g. read_file output), render as plain text
    if (typeof ev.result === 'string') {
        return renderPlainTextBlock(ev.result);
    }
    // Backend wraps non-dict/non-list results as {"data": "string"} — unwrap for display
    if (typeof ev.result === 'object' && ev.result !== null && Object.keys(ev.result).length === 1 && 'data' in ev.result && typeof ev.result.data === 'string') {
        return renderPlainTextBlock(ev.result.data);
    }
    return `<div class="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-1">${chatEscapeHtml(summarizeToolResult(ev.result))}</div>`;
}

function mergeToolResult(panel, ev) {
    // Find the first unresolved tool_call entry whose tool name matches the result.
    // This handles parallel tool calls correctly — each result updates its own entry.
    const allToolCalls = panel.querySelectorAll('.timeline-entry[data-tool-type="tool_call"]');
    let toolCallEntry = null;
    for (const entry of allToolCalls) {
        if (entry.getAttribute('data-tool-name') === ev.tool &&
            !entry.querySelector('.tl-detail > .mt-2')) {
            toolCallEntry = entry;
            break;
        }
    }
    // Fallback: if no matching unresolved entry found, use the last one (backward compat)
    if (!toolCallEntry) {
        toolCallEntry = allToolCalls[allToolCalls.length - 1];
    }
    if (!toolCallEntry) return;

    // Remove spinner and restore border (deactivate)
    deactivateTimelineEntry(toolCallEntry);

    // Update border color to reflect result
    const newBorder = ev.error ? 'border-red-300' : 'border-green-300';
    toolCallEntry.classList.remove('border-blue-300', 'border-transparent');
    toolCallEntry.classList.add(newBorder);
    toolCallEntry.dataset.border = newBorder;

    // Update status icon in summary line
    const statusEl = toolCallEntry.querySelector('.tl-status');
    if (statusEl) {
        statusEl.innerHTML = ev.error
            ? `<span class="text-[14px] font-bold leading-none" style="color:#ef4444">&#10005;</span>`
            : `<span class="text-[14px] font-bold leading-none" style="color:#22c55e">&#10003;</span>`;
    }

    // Append result section into the detail div
    const detailDiv = toolCallEntry.querySelector('.tl-detail');
    if (detailDiv) {
        const resultLabelColor = ev.error ? 'text-red-400' : 'text-green-400';
        const wrapper = document.createElement('div');
        wrapper.className = 'mt-2 pt-2 border-t border-gray-100';
        wrapper.innerHTML = `<span class="text-[10px] uppercase tracking-wide ${resultLabelColor} font-semibold block mb-1">Result</span>${renderToolResultDetail(ev)}`;
        detailDiv.appendChild(wrapper);
    }
}

const THINKING_MAX_LINES = 25;

function renderThinkingContent(content) {
    const escaped = chatEscapeHtml(content);
    const lines = content.split('\n');
    if (lines.length <= THINKING_MAX_LINES) {
        return `<pre class="p-2 dark:text-purple-300 whitespace-pre-wrap break-words overflow-x-auto max-w-full text-purple-800 text-[10px] leading-relaxed">${escaped}</pre>`;
    }
    const shortLines = lines.slice(0, THINKING_MAX_LINES);
    const remaining = lines.length - THINKING_MAX_LINES;
    const shortHtml = shortLines.join('\n');
    const uid = 'tc-' + Math.random().toString(36).substr(2, 8);
    return `<pre class="whitespace-pre-wrap p-2 dark:text-purple-300 break-words overflow-x-auto max-w-full text-purple-800 text-[10px] leading-relaxed" id="${uid}" style="max-height: ${THINKING_MAX_LINES * 16}px; overflow: hidden; position: relative;">${chatEscapeHtml(shortHtml)}<span class="thinking-trim-fade absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-purple-50 to-transparent flex items-end justify-center pb-1"><button type="button" class="text-[10px] text-purple-500 hover:text-purple-700 font-medium cursor-pointer" onclick="var e=document.getElementById('${uid}');e.style.maxHeight='none';e.style.overflow='';this.parentElement.remove();">${remaining} more lines…</button></span></pre>`;
}

function renderTimelineEntry(ev, isActive, entryId) {
    let borderClass, icon, label, labelClass, summary, detailHtml, spinnerColor;
    let extraAttrs = '';

    if (ev.type === 'thinking') {
        borderClass = 'border-purple-300'; icon = '&#129504;'; label = 'Thinking';
        labelClass = 'text-purple-500'; spinnerColor = '#a855f7';
        summary = chatTruncateLine(ev.content, 80);
        let detailParts = [];
        detailParts.push(renderThinkingContent(ev.content));
        if (ev.args && ev.args.code) {
            detailParts.push(`<span class="text-[10px] uppercase tracking-wide text-purple-400 font-semibold">code:</span>`);
            detailParts.push(`<pre class="runpy-code-block mt-0.5">${highlightPython(ev.args.code)}</pre>`);
            const otherKeys = Object.keys(ev.args).filter(k => k !== 'code');
            if (otherKeys.length > 0) {
                for (const k of otherKeys) {
                    detailParts.push(`<span class="text-[10px] uppercase tracking-wide text-purple-400 font-semibold">${chatEscapeHtml(k)}:</span>`);
                    detailParts.push(`<span class="text-xs text-purple-600">${chatEscapeHtml(String(ev.args[k]))}</span>`);
                }
            }
        }
        detailHtml = detailParts.join('');

    } else if (ev.type === 'tool_call') {
        borderClass = 'border-blue-300'; icon = '&#128295;'; label = 'Tool Call';
        labelClass = 'text-blue-500'; spinnerColor = '#3b82f6';
        extraAttrs = ' data-tool-type="tool_call" data-tool-name="' + chatEscapeHtml(ev.tool) + '"';
        summary = ev.tool + '(' + chatTruncateLine(JSON.stringify(ev.args), 60) + ')';
        detailHtml = renderToolCallDetail(ev.tool, ev.args || {}, ev.param_types || {});

    } else if (ev.type === 'response') {
        borderClass = 'border-gray-300'; icon = '&#128172;'; label = 'Response';
        labelClass = 'text-gray-500'; spinnerColor = '#6b7280';
        summary = chatTruncateLine(ev.content, 80);
        detailHtml = `<pre class="whitespace-pre-wrap dark:text-gray-200 break-words overflow-x-auto max-w-full text-[11px] text-gray-700">${chatEscapeHtml(ev.content)}</pre>`;

    } else if (ev.type === 'retry') {
        borderClass = 'border-yellow-300'; icon = '&#128260;'; label = 'Mencoba Ulang';
        labelClass = 'text-yellow-600'; spinnerColor = '#f59e0b';
        summary = ev.message || `Mencoba ulang... (${ev.retry_count}/${ev.max_retries})`;
        detailHtml = '';

    } else {
        return '';
    }

    const activeBorder = isActive ? 'border-transparent' : borderClass;
    const idAttr = entryId ? ` id="${entryId}"` : '';
    const borderSpinnerHtml = isActive
        ? `<span class="tl-border-spinner"><span class="tool-spinner" style="border-color:rgba(0,0,0,0.08);border-top-color:${spinnerColor}"></span></span>`
        : '';
    // .tl-status: empty placeholder for tool_call; shows ✓ or ✗ when result arrives
    const statusSpan = ev.type === 'tool_call' ? `<span class="tl-status inline-flex items-center"></span>` : '';
    return `<div class="timeline-entry border-l-2 ${activeBorder} pl-3 py-1 relative" data-border="${borderClass}"${idAttr}${extraAttrs}>
        ${borderSpinnerHtml}<div class="flex items-center gap-1 cursor-pointer select-none"
             onclick="var b=this.nextElementSibling;b.classList.toggle('hidden');this.querySelector('.tl-chev').classList.toggle('rotated')">
            <span class="tl-chev tool-trace-chevron text-[9px] text-gray-300">&#9656;</span>
            <span class="text-[10px] font-semibold ${labelClass}">${icon}</span>
            ${statusSpan}<span class="text-[11px] text-gray-400 truncate max-w-[780px]">${chatEscapeHtml(summary)}</span>
        </div>
        <div class="tl-detail ml-5 hidden mt-1 overflow-x-hidden max-w-full">
            ${detailHtml}
        </div>
    </div>`;
}

function deactivateTimelineEntry(entryEl) {
    if (!entryEl) return;
    const savedBorder = entryEl.dataset.border;
    if (savedBorder) {
        entryEl.classList.remove('border-transparent');
        entryEl.classList.add(savedBorder);
    }
    const spinner = entryEl.querySelector('.tl-border-spinner');
    if (spinner) spinner.remove();
}

/* ==================== ChatUI Factory ==================== */

function ChatUI(config) {
    const cfg = Object.assign({
        containerId: 'chat-messages',
        userAlign: 'right',
        assistantAlign: 'left',
        showTimestamps: false,
        userBubbleClass: 'bg-indigo-800 text-white',
        assistantBubbleClass: 'bg-gray-200 text-gray-800',
        formatTimestamp: null,
        agentAvatarUrl: null,
    }, config);

    let _container = null;
    let _thinkingCounter = 0;
    let _activeEventSource = null;
    const _thinkingTimers = {};
    let _batchMode = false;

    function getContainer() {
        if (!_container) _container = document.getElementById(cfg.containerId);
        return _container;
    }

    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    function _alignClass(side) {
        return side === 'left' ? 'justify-start' : 'justify-end';
    }

    function _isNearBottom(threshold) {
        const c = getContainer();
        if (!c) return true;
        return c.scrollHeight - c.scrollTop - c.clientHeight < (threshold || 300);
    }

    function _smartScroll() {
        if (_batchMode) return;
        if (_isNearBottom(300)) {
            const c = getContainer();
            c.scrollTop = c.scrollHeight;
        }
    }

    function batchRender(fn) {
        _batchMode = true;
        try { fn(); } finally { _batchMode = false; }
        const c = getContainer();
        if (c) c.scrollTop = c.scrollHeight;
    }

    function _formatTs(ts) {
        if (!ts) return '';
        if (cfg.formatTimestamp) return cfg.formatTimestamp(ts);
        try {
            const d = new Date(ts);
            return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        } catch(e) { return ''; }
    }

    /* ---------- Public: message bubbles ---------- */

    function appendMessage(role, content, opts) {
        opts = opts || {};
        // Skip empty non-error messages to avoid blank bubbles (e.g. tool-call assistant turns)
        if (role !== 'error' && (!content || !content.trim())) return;
        const container = getContainer();

        // Remove empty-state placeholder if present
        const placeholder = container.querySelector('[data-empty-state]');
        if (placeholder) placeholder.remove();

        // Render thinking bubble first if timeline exists
        if (role === 'assistant' && opts.metadata && opts.metadata.timeline && opts.metadata.timeline.length > 0) {
            renderThinkingBubble(opts.metadata.timeline, opts.metadata.thinking_duration);
        }

        const isUser = role === 'user';
        const isError = role === 'error';
        const isSystem = /^\[system/i.test(content);
        const isSystemUser = isUser && /^\[system(?:\/[^\]]*)?\]/i.test(content);
        const isAgentUser = isUser && /^\[AGENT\/[^\]]+\]/i.test(content);
        const align = isUser ? _alignClass(cfg.userAlign) : _alignClass(cfg.assistantAlign);

        let bubbleClass, wrapClass, renderedContent;
        if (isAgentUser) {
            bubbleClass = 'bg-blue-100 text-blue-900 border border-blue-300';
            wrapClass = 'whitespace-pre-wrap';
            const agentMatch = content.match(/^(\[AGENT\/[^\]]+\])\s*/i);
            const agentTag = agentMatch ? agentMatch[1] : '';
            const agentContent = agentTag ? content.slice(agentMatch[0].length) : content;
            renderedContent = (agentTag ? '<span class="text-xs font-semibold text-blue-500 mr-1.5">' + chatEscapeHtml(agentTag) + '</span>' : '') + chatEscapeHtml(agentContent);
        } else if (isSystemUser) {
            bubbleClass = 'bg-orange-100 text-orange-900 border border-orange-300';
            wrapClass = '';
            const sysMatch = content.match(/^(\[(?:SYSTEM(?:\/[^\]]*)?|System\/[^\]]*)\])\s*/);
            const sysTag = sysMatch ? sysMatch[1] : '';
            const sysContent = sysTag ? content.slice(sysMatch[0].length) : content;
            const tagHtml = sysTag ? '<span class="text-xs font-semibold text-orange-500 mr-1.5">' + chatEscapeHtml(sysTag) + '</span>' : '';
            const sysPreviewText = sysContent.replace(/\n/g, ' ').trim();
            const sysTruncated = sysPreviewText.length > 120 ? sysPreviewText.substring(0, 120) + '…' : sysPreviewText;
            const sysNeedsCollapse = sysPreviewText.length > 120;
            const sysId2 = 'sys-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
            renderedContent =
                '<div class="sys-balloon" data-sys-id="' + sysId2 + '">' +
                    '<div class="sys-balloon-header cursor-pointer flex items-start gap-1.5 whitespace-pre-wrap" onclick="toggleSysBalloon(\'' + sysId2 + '\')">' +
                        '<span class="sys-balloon-content block">' + tagHtml + chatEscapeHtml(sysTruncated) + '</span>' +
                        (sysNeedsCollapse ? '<span class="sys-chevron text-orange-400 text-[10px] flex-shrink-0 mt-0.5">&#9660;</span>' : '') +
                    '</div>' +
                    '<div class="sys-balloon-full whitespace-pre-wrap" style="display:none;overflow:hidden;">' + tagHtml + chatEscapeHtml(sysContent) + '</div>' +
                '</div>';
        } else if (isUser) {
            bubbleClass = cfg.userBubbleClass;
            wrapClass = 'whitespace-pre-wrap';
            renderedContent = chatEscapeHtml(content);
        } else if (isError) {
            bubbleClass = 'bg-red-50 text-red-700 border border-red-200';
            wrapClass = '';
            renderedContent = chatEscapeHtml(content);
        } else if (isSystem) {
            bubbleClass = 'bg-orange-200 text-gray-600 border-gray-400';
            wrapClass = '';
            const sysMatch = content.match(/^\[system[^\]]*\]\s*/i);
            const sysTag = sysMatch ? sysMatch[0].trim() : '[SYSTEM]';
            const sysContent = content.replace(/^\[system[^\]]*\]\s*/i, '');
            const previewText = sysContent.replace(/\n/g, ' ').trim();
            const truncated = previewText.length > 120 ? previewText.substring(0, 120) + '…' : previewText;
            const previewHtml = '<span class="text-xs font-semibold text-gray-500 mr-1.5">' + chatEscapeHtml(sysTag) + '</span>' + chatEscapeHtml(truncated);

            const sysId = 'sys-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
            const needsCollapse = previewText.length > 120;
            renderedContent =
                '<div class="sys-balloon" data-sys-id="' + sysId + '">' +
                    '<div class="sys-balloon-header cursor-pointer flex items-start gap-1.5 whitespace-pre-wrap" onclick="toggleSysBalloon(\'' + sysId + '\')">' +
                        '<span class="sys-balloon-content block">' + previewHtml + '</span>' +
                        (needsCollapse ? '<span class="sys-chevron text-gray-400 text-[10px] flex-shrink-0 mt-0.5">&#9660;</span>' : '') +
                    '</div>' +
                    '<div class="sys-balloon-full whitespace-pre-wrap" style="display:none;overflow:hidden;"><span class="text-xs font-semibold text-gray-500 mr-1.5">' + chatEscapeHtml(sysTag) + '</span>' + chatEscapeHtml(sysContent) + '</div>' +
                '</div>';
        } else {
            bubbleClass = cfg.assistantBubbleClass;
            wrapClass = 'chat-prose';
            renderedContent = marked.parse(content || '').replace(/<table/g, '<div class="table-wrapper"><table').replace(/<\/table>/g, '</table></div>');
        }

        const errorIcon = isError
            ? '<svg class="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd"/></svg>'
            : '';

        let timestampHtml = '';
        if (cfg.showTimestamps && opts.timestamp) {
            const tsStr = _formatTs(opts.timestamp);
            if (tsStr) {
                const tsAlign = isUser
                    ? (cfg.userAlign === 'left' ? 'text-left' : 'text-right')
                    : (cfg.assistantAlign === 'left' ? 'text-left' : 'text-right');
                timestampHtml = `<div class="text-[10px] text-gray-300 mt-0.5 ${tsAlign} px-1">${chatEscapeHtml(tsStr)}</div>`;
            }
        }

        const isAssistant = role === 'assistant';
        const avatarHtml = (isAssistant && cfg.agentAvatarUrl)
            ? `<img src="${cfg.agentAvatarUrl}" alt="" class="w-7 h-7 rounded-full object-cover flex-shrink-0 mt-1 bg-indigo-50 dark:bg-indigo-900/20" onerror="this.onerror=null;this.style.display='none'">`
            : '';
        const wrapper = document.createElement('div');
        wrapper.className = `flex ${align} ${avatarHtml ? 'items-start gap-2' : ''}`;
        if (isError) {
            wrapper.innerHTML = `${avatarHtml}<div class="max-w-[80%]"><div class="${bubbleClass} rounded-lg px-4 py-2 text-sm flex items-start gap-2">${errorIcon}<span class="${wrapClass}">${renderedContent}</span></div>${timestampHtml}</div>`;
        } else {
            wrapper.innerHTML = `${avatarHtml}<div class="max-w-[80%]"><div class="${bubbleClass} rounded-2xl px-4 py-2.5 text-sm ${wrapClass} break-words">${renderedContent}</div>${timestampHtml}</div>`;
        }
        container.appendChild(wrapper);
        _smartScroll();
    }

    /* ---------- Public: thinking bubble (streaming) ---------- */

    const _STALE_TIMEOUT_MS = 3 * 60 * 1000; // 3 minutes
    const _staleTimers = {};
    let _activeSpinnerId = null; // currently-spinning bubble ID; cleared on finalize/remove

    function showThinkingIndicator(startTs) {
        const container = getContainer();

        // Guard: never create a second spinner if one is already active
        if (_activeSpinnerId) {
            const existingWrapper = document.getElementById(_activeSpinnerId + '-wrapper');
            if (existingWrapper && existingWrapper.querySelector('.thinking-spinner')) {
                return _activeSpinnerId; // return existing active bubble
            }
            _activeSpinnerId = null; // stale reference — clear it
        }

        const id = 'thinking-' + Date.now() + '-' + (++_thinkingCounter);
        const detailId = id + '-detail';
        const thinkAlign = _alignClass(cfg.assistantAlign);

        const avatarHtml = cfg.agentAvatarUrl
            ? `<img src="${cfg.agentAvatarUrl}" alt="" class="w-7 h-7 rounded-full object-cover flex-shrink-0 mt-1 bg-indigo-50 dark:bg-indigo-900/20" onerror="this.onerror=null;this.style.display='none'">`
            : '';

        const wrapper = document.createElement('div');
        wrapper.id = id + '-wrapper';
        wrapper.className = `flex ${thinkAlign} ${avatarHtml ? 'items-start gap-2' : ''}`;
        wrapper.innerHTML = `${avatarHtml}
            <div class="thinking-bubble flex items-center gap-2 rounded-lg px-3 py-2 text-xs border border-purple-200 bg-purple-50 dark:border-purple-800 dark:bg-purple-900/60 cursor-pointer"
                 data-detail="${detailId}">
                <span>&#129504;</span>
                <span class="font-medium text-purple-700 dark:text-purple-200">Thinking</span>
                <span class="thinking-step-count text-purple-500 dark:text-purple-300 text-[10px] ml-0.5 hidden"></span>
                <span class="thinking-spinner"><span class="tool-spinner"></span></span>
                <span class="thinking-timer-inline text-purple-500 dark:text-purple-400 text-[10px]">0.0 s</span>
                <span class="ml-1 text-purple-500 dark:text-purple-300 tool-trace-chevron text-sm">&#9656;</span>
            </div>`;
        wrapper.querySelector('.thinking-bubble').addEventListener('click', function() {
            const detail = document.getElementById(this.getAttribute('data-detail'));
            if (!detail) return;
            detail.querySelector('.timeline-panel').classList.toggle('hidden');
            this.querySelector('.tool-trace-chevron').classList.toggle('rotated');
        });

        const detail = document.createElement('div');
        detail.className = `flex ${thinkAlign}`;
        detail.id = detailId;
        detail.innerHTML = `
            <div class="ml-5 max-w-[80%]">
                <div class="timeline-panel hidden space-y-0.5 py-0.5"></div>
            </div>`;

        container.appendChild(wrapper);
        wrapper.after(detail);

        const startTime = startTs || Date.now();
        const timerInline = wrapper.querySelector('.thinking-timer-inline');
        _thinkingTimers[id] = setInterval(() => {
            const elapsed = Date.now() - startTime;
            if (timerInline) timerInline.textContent = (elapsed / 1000).toFixed(1) + ' s';
        }, 100);

        // Stale spinner guard: auto-finalize if no activity within timeout
        _staleTimers[id] = setTimeout(() => {
            finalizeThinkingBubble(id);
        }, _STALE_TIMEOUT_MS);

        _activeSpinnerId = id;
        _smartScroll();
        return id;
    }

    function removeThinkingIndicator(id) {
        if (_staleTimers[id]) { clearTimeout(_staleTimers[id]); delete _staleTimers[id]; }
        if (_activeSpinnerId === id) _activeSpinnerId = null;
        const wrapper = document.getElementById(id + '-wrapper');
        if (wrapper) wrapper.remove();
        const detail = document.getElementById(id + '-detail');
        if (detail) detail.remove();
    }

    /**
     * Mutate the bubble header to signal the agent is paused waiting for approval.
     * Call setApprovalPendingState(id, false) to restore the normal Thinking state.
     */
    function setApprovalPendingState(id, pending) {
        const wrapper = document.getElementById(id + '-wrapper');
        if (!wrapper) return;
        const bubble = wrapper.querySelector('.thinking-bubble');
        if (!bubble) return;

        if (pending) {
            bubble.classList.remove('border-purple-200', 'bg-purple-50', 'dark:border-purple-800', 'dark:bg-purple-900/60');
            bubble.classList.add('border-orange-300', 'bg-orange-50', 'dark:border-orange-700', 'dark:bg-orange-900/60', 'approval-pending-bubble');
            bubble.querySelector('span:first-child').innerHTML = '&#128274;';
            const labelEl = bubble.querySelector('.font-medium');
            if (labelEl) {
                labelEl.textContent = 'Menunggu Approval';
                labelEl.classList.remove('text-purple-700', 'dark:text-purple-200');
                labelEl.classList.add('text-orange-700', 'dark:text-orange-200');
            }
            const spinner = bubble.querySelector('.thinking-spinner .tool-spinner');
            if (spinner) {
                spinner.style.borderColor = 'rgba(249,115,22,0.15)';
                spinner.style.borderTopColor = '#f97316';
            }
            const timer = bubble.querySelector('.thinking-timer-inline');
            if (timer) {
                timer.classList.remove('text-purple-500', 'dark:text-purple-400');
                timer.classList.add('text-orange-500', 'dark:text-orange-400');
            }
        } else {
            bubble.classList.add('border-purple-200', 'bg-purple-50', 'dark:border-purple-800', 'dark:bg-purple-900/60');
            bubble.classList.remove('border-orange-300', 'bg-orange-50', 'dark:border-orange-700', 'dark:bg-orange-900/60', 'approval-pending-bubble');
            bubble.querySelector('span:first-child').innerHTML = '&#129504;';
            const labelEl = bubble.querySelector('.font-medium');
            if (labelEl) {
                labelEl.textContent = 'Thinking';
                labelEl.classList.add('text-purple-700', 'dark:text-purple-200');
                labelEl.classList.remove('text-orange-700', 'dark:text-orange-200');
            }
            const spinner = bubble.querySelector('.thinking-spinner .tool-spinner');
            if (spinner) {
                spinner.style.borderColor = '';
                spinner.style.borderTopColor = '';
            }
            const timer = bubble.querySelector('.thinking-timer-inline');
            if (timer) {
                timer.classList.add('text-purple-500', 'dark:text-purple-400');
                timer.classList.remove('text-orange-500', 'dark:text-orange-400');
            }
        }
    }

    function appendTimelineEntry(id, ev) {
        const detail = document.getElementById(id + '-detail');
        if (!detail) return;
        const panel = detail.querySelector('.timeline-panel');
        if (!panel) return;

        // tool_result is merged into the preceding tool_call entry — no new entry needed
        if (ev.type === 'tool_result') {
            mergeToolResult(panel, ev);
            // Show "Thinking..." row while waiting for the next LLM turn
            const existingPending = panel.querySelector('.tl-thinking-pending');
            if (existingPending) existingPending.remove();
            const pendingEl = document.createElement('div');
            pendingEl.className = 'tl-thinking-pending border-l-2 border-transparent pl-3 py-0.5 relative';
            pendingEl.innerHTML = `<span class="tl-border-spinner"><span class="tool-spinner" style="border-color:rgba(168,85,247,0.15);border-top-color:#a855f7"></span></span><span class="text-[11px] text-purple-500 dark:text-purple-400">Thinking...</span>`;
            panel.appendChild(pendingEl);
            _smartScroll();
            return;
        }

        // Remove "Thinking..." placeholder when a new event arrives
        const pendingThinking = panel.querySelector('.tl-thinking-pending');
        if (pendingThinking) pendingThinking.remove();

        // Deactivate previous last entry (it's now done)
        const prevLast = panel.querySelector('.timeline-entry:last-child');
        if (prevLast) deactivateTimelineEntry(prevLast);

        const entryId = id + '-entry-' + panel.querySelectorAll('.timeline-entry').length;
        const html = renderTimelineEntry(ev, true, entryId);
        if (!html) return;

        const entry = document.createElement('div');
        entry.innerHTML = html;
        panel.appendChild(entry.firstElementChild);

        const wrapper = document.getElementById(id + '-wrapper');
        if (wrapper) {
            const stepEl = wrapper.querySelector('.thinking-step-count');
            if (stepEl) {
                const count = panel.querySelectorAll('.timeline-entry[data-tool-type="tool_call"]').length;
                stepEl.textContent = count + ' tools';
                if (count > 0) {
                    stepEl.classList.remove('hidden');
                }
            }
        }

        _smartScroll();
    }

    function finalizeThinkingBubble(id, duration) {
        if (_thinkingTimers[id]) {
            clearInterval(_thinkingTimers[id]);
            delete _thinkingTimers[id];
        }
        if (_staleTimers[id]) { clearTimeout(_staleTimers[id]); delete _staleTimers[id]; }
        if (_activeSpinnerId === id) _activeSpinnerId = null;
        const wrapper = document.getElementById(id + '-wrapper');
        if (!wrapper) return;
        const spinnerEl = wrapper.querySelector('.thinking-spinner');
        if (spinnerEl) spinnerEl.remove();

        // If a persisted duration is provided, freeze the timer display to it;
        // otherwise hide the timer so old records don't misleadingly show "0.0 s"
        const timerEl = wrapper.querySelector('.thinking-timer-inline');
        if (timerEl) {
            if (duration != null) {
                timerEl.textContent = Number(duration).toFixed(1) + ' s';
            } else {
                timerEl.classList.add('hidden');
            }
        }

        const detail = document.getElementById(id + '-detail');
        if (detail) {
            const pendingThinking = detail.querySelector('.tl-thinking-pending');
            if (pendingThinking) pendingThinking.remove();
            const lastEntry = detail.querySelector('.timeline-entry:last-child');
            if (lastEntry) deactivateTimelineEntry(lastEntry);
        }
        const count = detail ? detail.querySelectorAll('.timeline-entry').length : 0;
        if (count === 0) removeThinkingIndicator(id);
    }

    function getTimelineEntryCount(id) {
        const detail = document.getElementById(id + '-detail');
        if (!detail) return 0;
        return detail.querySelectorAll('.timeline-entry').length;
    }

    function resolveThinkingIndicator(id, timeline, duration) {
        for (const ev of timeline) {
            appendTimelineEntry(id, ev);
        }
        finalizeThinkingBubble(id, duration);
    }

    function renderThinkingBubble(timeline, duration) {
        const id = showThinkingIndicator();
        resolveThinkingIndicator(id, timeline, duration);
    }

    /* ---------- Public: tool trace animation ---------- */

    async function animateToolTrace(trace) {
        const container = getContainer();
        for (let i = 0; i < trace.length; i++) {
            const t = trace[i];
            const hasError = t.result && t.result.error;
            const id = 'tool-trace-' + Date.now() + '-' + i;
            const detailId = id + '-detail';
            const traceAlign = _alignClass(cfg.assistantAlign);

            const wrapper = document.createElement('div');
            wrapper.className = `flex ${traceAlign}`;
            wrapper.innerHTML = `
                <div id="${id}" class="tool-trace-bubble flex items-center gap-2 rounded-lg px-3 py-2 text-xs border border-gray-200 bg-gray-50 cursor-pointer"
                     data-detail="${detailId}">
                    <span class="tool-trace-icon">&#128295;</span>
                    <span class="font-mono font-medium text-gray-700">${chatEscapeHtml(t.tool)}</span>
                    <span class="tool-trace-status"><span class="tool-spinner"></span></span>
                    <span class="ml-1 text-gray-300 tool-trace-chevron text-[10px]">&#9656;</span>
                </div>`;
            wrapper.querySelector('.tool-trace-bubble').addEventListener('click', function() {
                _toggleToolDetail(this);
            });
            container.appendChild(wrapper);

            const argsHtml = chatEscapeHtml(JSON.stringify(t.args, null, 2));
            let resultHtml = '';
            const isRunpy = t.tool === 'runpy' && typeof t.result === 'object' && !hasError && t.result.exit_code !== undefined;

            if (isRunpy) {
                const r = t.result;
                const hasStdout = r.stdout && r.stdout.trim().length > 0;
                const hasStderr = r.stderr && r.stderr.trim().length > 0;
                const hasErrorExit = r.exit_code !== 0;
                const statusColor = hasErrorExit ? 'text-red-600' : 'text-green-600';
                const statusBg = hasErrorExit ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200';
                const statusIcon = hasErrorExit ? '&#10060;' : '&#9989;';
                let runpyArgsParts = [];
                if (t.args && t.args.code) {
                    runpyArgsParts.push(`<span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">code:</span>`);
                    runpyArgsParts.push(`<pre class="runpy-code-block mt-0.5">${highlightPython(t.args.code)}</pre>`);
                    const otherKeys = Object.keys(t.args).filter(k => k !== 'code');
                    if (otherKeys.length > 0) {
                        for (const k of otherKeys) {
                            runpyArgsParts.push(`<span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">${chatEscapeHtml(k)}:</span>`);
                            runpyArgsParts.push(`<span class="text-xs text-gray-600">${chatEscapeHtml(String(t.args[k]))}</span>`);
                        }
                    }
                } else {
                    runpyArgsParts.push(`<span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Arguments</span>`);
                    runpyArgsParts.push(`<pre class="mt-1 bg-gray-50 rounded p-2 overflow-x-auto text-gray-600">${argsHtml}</pre>`);
                }
                resultHtml += `<div class="mb-1">${runpyArgsParts.join('')}</div>`;
                resultHtml += `<div><span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Result</span>
                    <div class="flex items-center gap-2 mt-1 text-[10px] font-mono ${statusColor} ${statusBg} border rounded px-2 py-1">
                        <span>${statusIcon} exit: ${chatEscapeHtml(String(r.exit_code))}</span>
                        <span class="text-gray-400">|</span>
                        <span>time: ${chatEscapeHtml(String(r.execution_time))}s</span>
                        ${r.available_helpers ? `<span class="text-gray-400">|</span><span class="text-gray-500">${Object.keys(r.available_helpers).length} helpers</span>` : ''}
                    </div>`;
                if (hasStdout) resultHtml += `<div class="mt-1"><span class="text-[10px] font-semibold text-gray-500">stdout</span><pre class="mt-0.5 bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto font-mono text-gray-800 max-h-[200px]">${chatEscapeHtml(r.stdout)}</pre></div>`;
                if (hasStderr) resultHtml += `<div class="mt-1"><span class="text-[10px] font-semibold text-red-500">stderr</span><pre class="mt-0.5 bg-red-50 border border-red-200 rounded p-2 overflow-x-auto font-mono text-red-700 max-h-[200px]">${chatEscapeHtml(r.stderr)}</pre></div>`;
                if (!hasStdout && !hasStderr) resultHtml += `<div class="mt-1 text-xs text-gray-400 italic">No output</div>`;
                resultHtml += `</div>`;
            } else if ((t.tool === 'bash' || (!t.tool && t.result && t.result.exit_code !== undefined)) && typeof t.result === 'object' && !hasError && t.result.exit_code !== undefined) {
                // Bash: treat stdout as plain text, not JSON
                const r = t.result;
                const bStdout = r.stdout && r.stdout.trim().length > 0;
                const bStderr = r.stderr && r.stderr.trim().length > 0;
                const bError = r.exit_code !== 0;
                const bColor = bError ? 'text-red-600' : 'text-green-600';
                const bBg = bError ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200';
                const bIcon = bError ? '&#10060;' : '&#9989;';
                let bashParts = [];
                if (t.args && t.args.script) {
                    bashParts.push(`<span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">script:</span>`);
                    bashParts.push(`<pre class="mt-0.5 bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto text-gray-600 text-xs font-mono">${chatEscapeHtml(t.args.script)}</pre>`);
                }
                bashParts.push(`<div class="mt-1"><span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Result</span>`);
                bashParts.push(`<div class="flex items-center gap-2 mt-1 text-[10px] font-mono ${bColor} ${bBg} border rounded px-2 py-1">`);
                bashParts.push(`<span>${bIcon} exit: ${chatEscapeHtml(String(r.exit_code))}</span>`);
                bashParts.push(`<span class="text-gray-400">|</span>`);
                bashParts.push(`<span>time: ${chatEscapeHtml(String(r.execution_time))}s</span>`);
                bashParts.push(`</div>`);
                if (bStdout) bashParts.push(`<div class="mt-1"><span class="text-[10px] font-semibold text-gray-500">stdout</span><pre class="mt-0.5 border rounded p-2 overflow-x-auto font-mono max-h-[200px] whitespace-pre-wrap" style="background-color:#0a0b0c;color:#54ae54;border-color:#1a1b1c">${chatEscapeHtml(r.stdout)}</pre></div>`);
                if (bStderr) bashParts.push(`<div class="mt-1"><span class="text-[10px] font-semibold text-red-500">stderr</span><pre class="mt-0.5 bg-red-50 border border-red-200 rounded p-2 overflow-x-auto font-mono text-red-700 max-h-[200px] whitespace-pre-wrap">${chatEscapeHtml(r.stderr)}</pre></div>`);
                if (!bStdout && !bStderr) bashParts.push(`<div class="mt-1 text-xs text-gray-400 italic">No output</div>`);
                bashParts.push(`</div>`);
                resultHtml = `<div class="mb-1">${bashParts.join('')}</div>`;
            } else {
                let nonRunpyParts = [];
                if (t.args && t.args.code) {
                    nonRunpyParts.push(`<span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">code:</span>`);
                    nonRunpyParts.push(`<pre class="runpy-code-block mt-0.5">${highlightPython(t.args.code)}</pre>`);
                    const otherKeys = Object.keys(t.args).filter(k => k !== 'code');
                    if (otherKeys.length > 0) {
                        for (const k of otherKeys) {
                            nonRunpyParts.push(`<span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">${chatEscapeHtml(k)}:</span>`);
                            nonRunpyParts.push(`<span class="text-xs text-gray-600">${chatEscapeHtml(String(t.args[k]))}</span>`);
                        }
                    }
                } else {
                    nonRunpyParts.push(`<span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Arguments</span>`);
                    nonRunpyParts.push(`<pre class="mt-1 bg-gray-50 rounded p-2 overflow-x-auto text-gray-600">${argsHtml}</pre>`);
                }
                nonRunpyParts.push(`<span class="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Result</span>`);
                nonRunpyParts.push(`<pre class="mt-1 rounded p-2 overflow-x-auto ${hasError ? 'bg-red-50 text-red-600' : 'bg-gray-50 text-gray-600'}">${chatEscapeHtml(JSON.stringify(t.result, null, 2))}</pre>`);
                resultHtml = `<div class="mb-1">${nonRunpyParts.join('')}</div>`;
            }

            const detail = document.createElement('div');
            detail.className = `flex ${traceAlign}`;
            detail.id = detailId;
            detail.innerHTML = `<div class="tool-trace-detail-panel hidden ml-5 max-w-[75%] text-xs border-l-2 border-gray-200 pl-3 py-1 mb-1">${resultHtml}</div>`;
            container.appendChild(detail);
            _smartScroll();

            await sleep(400);
            const bubble = document.getElementById(id);
            const statusEl = bubble.querySelector('.tool-trace-status');
            if (hasError) {
                statusEl.innerHTML = '&#10060;';
                bubble.classList.add('border-red-200', 'bg-red-50');
                bubble.classList.remove('border-gray-200', 'bg-gray-50');
            } else {
                statusEl.innerHTML = '&#9989;';
            }
            _smartScroll();
            if (i < trace.length - 1) await sleep(200);
        }
    }

    function _toggleToolDetail(bubble) {
        const detailId = bubble.getAttribute('data-detail');
        if (!detailId) return;
        const detailRow = document.getElementById(detailId);
        if (!detailRow) return;
        const panel = detailRow.querySelector('.tool-trace-detail-panel');
        if (!panel) return;
        panel.classList.toggle('hidden');
        const chevron = bubble.querySelector('.tool-trace-chevron');
        if (chevron) chevron.classList.toggle('rotated');
    }

    /* ---------- Approval card ---------- */

    function appendApprovalCard(id, data, agentId) {
        if (data.approval_id && document.querySelector('[data-approval-id="' + data.approval_id + '"]')) return;
        const detail = document.getElementById(id + '-detail');
        if (!detail) return;
        const panel = detail.querySelector('.timeline-panel');
        if (!panel) return;

        const riskLevel = (data.approval_info && data.approval_info.risk_level) || 'medium';
        const riskColor = riskLevel === 'high' ? 'text-red-500 dark:text-red-400' : riskLevel === 'low' ? 'text-yellow-500 dark:text-yellow-400' : 'text-orange-500 dark:text-orange-400';
        const riskBg = riskLevel === 'high' ? 'bg-red-50/80 border-red-300 dark:bg-red-950/40 dark:border-red-800' : riskLevel === 'low' ? 'bg-yellow-50/80 border-yellow-300 dark:bg-yellow-950/40 dark:border-yellow-800' : 'bg-orange-50/80 border-orange-300 dark:bg-orange-950/40 dark:border-orange-800';
        const description = (data.approval_info && data.approval_info.description) || 'This action requires careful consideration.';
        const reasons = (data.reasons || []).map(r => `<li>${chatEscapeHtml(r)}</li>`).join('');
        const toolArgs = data.tool_args || {};
        const codeSnippet = toolArgs.script || toolArgs.code || null;
        const codeLang = toolArgs.script !== undefined ? 'bash' : 'python';

        const card = document.createElement('div');
        card.className = `approval-card timeline-entry border rounded-lg mb-2 ${riskBg}`;
        card.dataset.approvalId = data.approval_id;
        card.innerHTML = `
            <div class="approval-summary hidden items-center gap-2 px-3 py-2 cursor-pointer select-none hover:opacity-80 transition-opacity" title="Click to expand">
                <span class="approval-summary-icon text-xs font-bold"></span>
                <span class="text-xs text-gray-600 dark:text-gray-300"><span class="font-semibold">Tool:</span> <code class="bg-white/60 dark:bg-gray-700/60 px-1 rounded">${chatEscapeHtml(data.tool || '')}</code></span>
                <span class="ml-auto text-[10px] text-gray-400 dark:text-gray-400 flex items-center gap-1">details <svg class="approval-chevron inline w-3 h-3 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg></span>
            </div>
            <div class="approval-details p-3">
                <div class="flex items-center gap-2 mb-2">
                    <span class="text-sm font-semibold ${riskColor}">&#9888; Approval Required</span>
                    <span class="text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded ${riskColor} border border-current">${chatEscapeHtml(riskLevel)}</span>
                </div>
                <div class="text-xs text-gray-700 dark:text-gray-200 mb-1"><span class="font-semibold">Tool:</span> <code class="bg-white/60 dark:bg-gray-700/60 px-1 rounded">${chatEscapeHtml(data.tool || '')}</code></div>
                <div class="text-xs text-gray-600 dark:text-gray-300 mb-2">${chatEscapeHtml(description)}</div>
                ${reasons ? `<ul class="text-xs text-gray-600 dark:text-gray-300 list-disc list-inside mb-2 space-y-0.5">${reasons}</ul>` : ''}
                ${codeSnippet ? `<div class="mb-2"><div class="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Code <span class="font-normal text-gray-400 dark:text-gray-500">(${codeLang})</span></div><pre class="text-xs bg-gray-900 text-gray-100 rounded p-2 overflow-auto max-h-48 whitespace-pre-wrap break-all"><code>${chatEscapeHtml(codeSnippet)}</code></pre></div>` : ''}
                <div class="approval-actions flex gap-2 mt-2">
                    <button class="approve-btn text-xs font-semibold px-3 py-1.5 rounded bg-green-600 text-white hover:bg-green-700 transition-colors" data-approval-id="${chatEscapeHtml(data.approval_id)}" data-agent-id="${chatEscapeHtml(agentId)}">Approve</button>
                    <button class="reject-btn text-xs font-semibold px-3 py-1.5 rounded bg-red-600 text-white hover:bg-red-700 transition-colors" data-approval-id="${chatEscapeHtml(data.approval_id)}" data-agent-id="${chatEscapeHtml(agentId)}">Reject</button>
                </div>
                <div class="approval-status text-xs font-semibold mt-1 hidden"></div>
            </div>
        `;

        card.querySelector('.approve-btn').addEventListener('click', async function () {
            await _resolveApproval(this.dataset.agentId, this.dataset.approvalId, 'approve', card);
        });
        card.querySelector('.reject-btn').addEventListener('click', async function () {
            await _resolveApproval(this.dataset.agentId, this.dataset.approvalId, 'reject', card);
        });

        card.querySelector('.approval-summary').addEventListener('click', function () {
            const details = card.querySelector('.approval-details');
            const chevron = card.querySelector('.approval-chevron');
            const isHidden = details.classList.toggle('hidden');
            if (chevron) chevron.style.transform = isHidden ? '' : 'rotate(180deg)';
        });

        panel.appendChild(card);
        _smartScroll();
    }

    async function _resolveApproval(agentId, approvalId, decision, card) {
        const actionsDiv = card.querySelector('.approval-actions');
        const statusDiv = card.querySelector('.approval-status');
        if (actionsDiv) actionsDiv.querySelectorAll('button').forEach(b => b.disabled = true);
        try {
            const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}/chat/approve`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({approval_id: approvalId, decision}),
            });
            if (res.ok) {
                _markApprovalCardResolved(card, decision, false);
            } else {
                const body = await res.json().catch(() => ({}));
                if (statusDiv) {
                    statusDiv.textContent = body.error || 'Failed to submit decision.';
                    statusDiv.className = 'approval-status text-xs font-semibold mt-1 text-red-600';
                    statusDiv.classList.remove('hidden');
                }
                if (actionsDiv) actionsDiv.querySelectorAll('button').forEach(b => b.disabled = false);
            }
        } catch (e) {
            if (statusDiv) {
                statusDiv.textContent = 'Network error. Please try again.';
                statusDiv.className = 'approval-status text-xs font-semibold mt-1 text-red-600';
                statusDiv.classList.remove('hidden');
            }
            if (actionsDiv) actionsDiv.querySelectorAll('button').forEach(b => b.disabled = false);
        }
    }

    function _markApprovalCardResolved(card, decision, timedOut) {
        const actionsDiv = card.querySelector('.approval-actions');
        const statusDiv = card.querySelector('.approval-status');
        const summaryDiv = card.querySelector('.approval-summary');
        const summaryIcon = card.querySelector('.approval-summary-icon');
        const detailsDiv = card.querySelector('.approval-details');

        if (actionsDiv) actionsDiv.classList.add('hidden');

        let statusText, statusClass, summaryIconHtml, summaryIconColor;
        if (timedOut) {
            statusText = 'Timed out — auto-rejected.';
            statusClass = 'approval-status text-xs font-semibold mt-1 text-gray-500';
            summaryIconHtml = '&#x23F1; Timed out';
            summaryIconColor = 'text-gray-500';
        } else if (decision === 'approve') {
            statusText = 'Approved — executing...';
            statusClass = 'approval-status text-xs font-semibold mt-1 text-green-600';
            summaryIconHtml = '&#10003; Approved';
            summaryIconColor = 'text-green-600';
        } else {
            statusText = 'Rejected.';
            statusClass = 'approval-status text-xs font-semibold mt-1 text-red-500';
            summaryIconHtml = '&#10007; Rejected';
            summaryIconColor = 'text-red-500';
        }

        if (statusDiv) {
            statusDiv.textContent = statusText;
            statusDiv.className = statusClass;
            statusDiv.classList.remove('hidden');
        }

        // Collapse to summary bar
        if (summaryIcon) {
            summaryIcon.innerHTML = summaryIconHtml;
            summaryIcon.className = `approval-summary-icon text-xs font-bold ${summaryIconColor}`;
        }
        if (summaryDiv) {
            summaryDiv.classList.remove('hidden');
            summaryDiv.classList.add('flex');
        }
        if (detailsDiv) detailsDiv.classList.add('hidden');
    }

    function resolveApprovalCard(data) {
        const card = document.querySelector(`.approval-card[data-approval-id="${CSS.escape(data.approval_id)}"]`);
        if (!card) return;
        _markApprovalCardResolved(card, data.decision, data.timed_out);
    }

    /* ---------- Public: SSE streaming ---------- */

    function connectThinkingStream(url, initialThinkingId, opts) {
        if (_activeEventSource) {
            _activeEventSource.close();
            _activeEventSource = null;
        }
        const es = new EventSource(url);
        _activeEventSource = es;

        // Extract agentId and sessionId from URL for gap-fill requests
        const agentIdMatch = url.match(/\/agents\/([^/?]+)\//);
        const agentId = agentIdMatch ? agentIdMatch[1] : '';
        const sessionId = new URL(url, window.location.origin).searchParams.get('session_id') || '';

        let currentThinkingId = initialThinkingId;
        let _lastSeq = 0;
        let _fillingGap = false;
        const _pendingQueue = [];

        function dispatchEvent(evtName, data) {
            if (evtName === 'thinking') {
                appendTimelineEntry(currentThinkingId, {type: 'thinking', content: data.content});
            } else if (evtName === 'tool_call_started') {
                appendTimelineEntry(currentThinkingId, {type: 'tool_call', tool: data.tool, args: data.args, param_types: data.param_types || {}});
            } else if (evtName === 'tool_executed') {
                appendTimelineEntry(currentThinkingId, {type: 'tool_result', tool: data.tool, result: data.result, error: data.error});
                if (['save_plan', 'set_mode', 'update_tasks', 'state'].includes(data.tool)) {
                    document.dispatchEvent(new CustomEvent('evonic:agent-state-changed', {detail: data}));
                }
            } else if (evtName === 'response_chunk') {
                if (data.is_final && data.content) {
                    appendTimelineEntry(currentThinkingId, {type: 'response', content: data.content});
                }
            } else if (evtName === 'approval_required') {
                document.dispatchEvent(new CustomEvent('evonic:approval-required', {detail: Object.assign({agent_id: agentId}, data)}));
            } else if (evtName === 'approval_resolved') {
                resolveApprovalCard(data);
                document.dispatchEvent(new CustomEvent('evonic:approval-resolved', {detail: data}));
            } else if (evtName === 'retry') {
                appendTimelineEntry(currentThinkingId, {type: 'retry', message: data.message, retry_count: data.retry_count, max_retries: data.max_retries});
            } else if (evtName === 'turn_begin') {
                // Create bubble now — LLM is actually about to be called
                if (!currentThinkingId) {
                    currentThinkingId = showThinkingIndicator(data.ts);
                    if (opts && opts.onThinkingId) opts.onThinkingId(currentThinkingId);
                }
            } else if (evtName === 'turn_split') {
                // Injected message was consumed by the loop — finalize current bubble, start new one
                finalizeThinkingBubble(currentThinkingId);
                currentThinkingId = showThinkingIndicator();
                markQueuedAsDelivered();
                if (opts && opts.onSplit) opts.onSplit(currentThinkingId);
            } else if (evtName === 'done') {
                finalizeThinkingBubble(currentThinkingId, data.thinking_duration);
                es.close();
                _activeEventSource = null;
            } else if (evtName === 'message_injected' || evtName === 'message_injection_applied') {
                // no-op: turn_split handles the delivered marking; these are informational
            } else if (evtName === 'session_clear') {
                clearContainer();
            }
        }

        async function fillGap(afterSeq, upToSeq) {
            try {
                const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}/chat/events?session_id=${encodeURIComponent(sessionId)}&after=${afterSeq}&up_to=${upToSeq}`);
                const body = await res.json();
                for (const ev of (body.events || [])) {
                    if (ev.seq <= _lastSeq) continue;
                    _lastSeq = ev.seq;
                    dispatchEvent(ev.event, ev.data);
                }
            } catch (err) {
                console.warn('[gap-fill] failed:', err);
                // Skip the gap rather than freezing
                _lastSeq = upToSeq - 1;
            }
        }

        function handleEvent(evtName, data) {
            const seq = data.seq || 0;
            if (_fillingGap) {
                _pendingQueue.push({evtName, data});
                return;
            }
            if (seq && _lastSeq > 0 && seq > _lastSeq + 1) {
                // Gap detected — buffer and fill
                _fillingGap = true;
                _pendingQueue.push({evtName, data});
                fillGap(_lastSeq, seq).then(() => {
                    _fillingGap = false;
                    while (_pendingQueue.length > 0) {
                        const item = _pendingQueue.shift();
                        const itemSeq = item.data.seq || 0;
                        if (itemSeq && itemSeq <= _lastSeq) continue;
                        if (itemSeq) _lastSeq = itemSeq;
                        dispatchEvent(item.evtName, item.data);
                    }
                });
                return;
            }
            if (seq) _lastSeq = seq;
            dispatchEvent(evtName, data);
        }

        for (const evtName of ['turn_begin', 'turn_split', 'thinking', 'tool_call_started', 'tool_executed', 'response_chunk', 'done', 'approval_required', 'approval_resolved', 'retry', 'message_injected', 'message_injection_applied', 'session_clear']) {
            es.addEventListener(evtName, e => {
                const data = JSON.parse(e.data);
                handleEvent(evtName, data);
            });
        }
        es.onerror = () => {
            es.close();
            _activeEventSource = null;
            // Reconnect after a short delay, resuming from the last seen sequence number.
            // This handles cases where the server closes the stream while the agent is
            // still running — without reconnect the thinking bubble would freeze.
            setTimeout(() => {
                if (_activeEventSource) return; // another stream already started
                const u = new URL(url, window.location.origin);
                if (_lastSeq > 0) u.searchParams.set('after', _lastSeq);
                connectThinkingStream(u.pathname + u.search, currentThinkingId, opts);
            }, 2000);
        };
        return es;
    }

    function closeStream() {
        if (_activeEventSource) {
            _activeEventSource.close();
            _activeEventSource = null;
        }
    }

    /* ---------- Public: queued message indicators ---------- */

    const _CLOCK_ICON = '<svg class="w-3 h-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>';
    const _CHECK_ICON = '<svg class="w-3 h-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5"/></svg>';

    function markLastUserBubbleQueued() {
        const container = getContainer();
        if (!container) return;
        // Find the last user bubble wrapper (flex justify-end)
        const wrappers = container.querySelectorAll('.flex.justify-end');
        if (!wrappers.length) return;
        const lastWrapper = wrappers[wrappers.length - 1];
        // Don't add duplicate indicators
        if (lastWrapper.querySelector('.queued-indicator')) return;
        const indicator = document.createElement('div');
        indicator.className = 'queued-indicator flex items-center gap-1 text-[10px] text-gray-400 mt-0.5 px-1 justify-end';
        indicator.innerHTML = _CLOCK_ICON + '<span>Queued</span>';
        lastWrapper.querySelector('div').appendChild(indicator);
    }

    function markQueuedAsDelivered() {
        const container = getContainer();
        if (!container) return;
        const indicators = container.querySelectorAll('.queued-indicator');
        indicators.forEach(el => {
            /* el.innerHTML = _CHECK_ICON + '<span>Injected</span>'; */
            el.classList.remove('text-gray-400');
            /* el.classList.add('text-green-500'); */
            setTimeout(() => {
                el.style.transition = 'opacity 0.5s';
                el.style.opacity = '0';
                setTimeout(() => el.remove(), 500);
            }, 2000);
        });
    }

    /* ---------- Public: container helpers ---------- */

    function clearContainer() {
        const container = getContainer();
        if (container) container.innerHTML = '';
    }

    function scrollToBottom() {
        const container = getContainer();
        if (container) container.scrollTop = container.scrollHeight;
    }

    /* ---------- System balloon toggle ---------- */

    function toggleSysBalloon(sysId) {
        const el = document.querySelector('[data-sys-id="' + sysId + '"]');
        if (!el) return;
        const header = el.querySelector('.sys-balloon-header');
        const full = el.querySelector('.sys-balloon-full');
        const chevron = el.querySelector('.sys-chevron');
        const preview = el.querySelector('.sys-balloon-content');
        if (!full) return;

        const isCollapsed = full.style.display === 'none' || full.style.display === '';
        if (isCollapsed) {
            // Expand: hide preview text, show full content with slide-down
            if (preview) preview.style.display = 'none';
            full.style.display = 'block';
            full.style.maxHeight = '0';
            full.style.transition = 'max-height 0.25s ease';
            requestAnimationFrame(function() {
                full.style.maxHeight = full.scrollHeight + 'px';
            });
            if (chevron) { chevron.style.transition = 'transform 0.2s ease'; chevron.style.transform = 'rotate(180deg)'; }
        } else {
            // Collapse: slide up then hide, restore preview
            full.style.maxHeight = full.scrollHeight + 'px';
            full.style.transition = 'max-height 0.25s ease';
            requestAnimationFrame(function() {
                full.style.maxHeight = '0';
            });
            full.addEventListener('transitionend', function handler() {
                full.removeEventListener('transitionend', handler);
                full.style.display = 'none';
                if (preview) preview.style.display = '';
            });
            if (chevron) { chevron.style.transition = 'transform 0.2s ease'; chevron.style.transform = ''; }
        }
    }

    window.toggleSysBalloon = toggleSysBalloon;

    /* ---------- Perspective ---------- */

    function setPerspective(perspective) {
        if (perspective === 'A') {
            cfg.userAlign = 'right';
            cfg.assistantAlign = 'left';
        } else {
            cfg.userAlign = 'left';
            cfg.assistantAlign = 'right';
        }
    }

    /* ---------- Public API ---------- */

    return {
        appendMessage,
        showThinkingIndicator,
        removeThinkingIndicator,
        appendTimelineEntry,
        finalizeThinkingBubble,
        resolveThinkingIndicator,
        renderThinkingBubble,
        animateToolTrace,
        connectThinkingStream,
        closeStream,
        clearContainer,
        scrollToBottom,
        batchRender,
        appendApprovalCard,
        resolveApprovalCard,
        setApprovalPendingState,
        markLastUserBubbleQueued,
        markQueuedAsDelivered,
        getTimelineEntryCount,
        hasActiveStream: () => !!_activeEventSource,
        isNearBottom: _isNearBottom,
        setPerspective,
    };
}
