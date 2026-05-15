/* ========================================
   Agent State Component (unified)
   Shared by agent_detail.html & sessions.html
   ======================================== */

function esc(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function renderAgentState(agentId, userId, containerIds, sessionId) {
    if (!agentId) return;
    try {
        let url = `/api/agents/${agentId}/chat/state?user_id=${encodeURIComponent(userId || 'web_test')}`;
        if (sessionId) url += `&session_id=${encodeURIComponent(sessionId)}`;
        const res = await fetch(url);
        if (!res.ok) { console.warn('[AgentState] API error:', res.status, res.statusText); return; }
        const data = await res.json();

        const empty = '<p class="text-sm text-gray-400 dark:text-gray-500 italic">No state yet.</p>';
        const hasAnyState = data.focus ||
            (data.states && Object.keys(data.states).length > 0);
        if (!hasAnyState) {
            (Array.isArray(containerIds) ? containerIds : [containerIds]).forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = empty;
            });
            return;
        }

        // Build status cards row (Focus)
        let cards = '';

        // Focus badge
        if (data.focus) {
            const reasonText = data.focus_reason ? ` — ${esc(data.focus_reason)}` : '';
            cards += `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 ml-1">Focus${reasonText}</span>`;
        }

        // TODO: Debug feature - dump raw AgentState JSON for verification
        const rawJson = JSON.stringify(data, null, 2);

        let html = `<div class="space-y-2 text-sm">`;

        // Status cards row
        html += `<div class="flex flex-wrap gap-1">${cards}</div>`;

        // Plugin states section
        if (data.states && Object.keys(data.states).length > 0) {
            html += `<div class="border-t border-gray-100 dark:border-gray-700 pt-2"><div class="text-gray-500 dark:text-gray-400 font-medium mb-1 text-xs uppercase tracking-wide">Plugin States</div><ul class="space-y-1">`;
            for (const [ns, slot] of Object.entries(data.states)) {
                const stateVal = slot.state || 'unknown';
                const dataStr = slot.data ? JSON.stringify(slot.data) : '';
                html += `<li><div class="flex items-center gap-1"><span class="font-medium text-xs text-gray-700 dark:text-gray-200">${esc(ns)}:</span><code class="text-xs bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">${esc(stateVal)}</code></div>`;
                if (dataStr) {
                    html += `<div class="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5 font-mono break-all">${esc(dataStr)}</div>`;
                }
                html += `</li>`;
            }
            html += `</ul></div>`;
        }


        // TODO: Debug feature - dump raw AgentState JSON for verification
        html += `<div class="mt-2 pt-2 border-t border-gray-100 dark:border-gray-700">`;
        html += `<div class="flex justify-end">`;
        html += `<button onclick="this.parentElement.nextElementSibling.classList.toggle('hidden');this.textContent=this.parentElement.nextElementSibling.classList.contains('hidden')?'Show Raw JSON':'Hide Raw JSON'" class="text-[10px] text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 underline cursor-pointer">Show Raw JSON</button>`;
        html += `</div>`;
        html += `<pre class="hidden mt-1 rounded p-2 text-[10px] font-mono overflow-x-auto whitespace-pre-wrap break-all max-h-40 overflow-y-auto">${esc(rawJson)}</pre>`;
        html += `</div>`;

        html += `</div>`;

        (Array.isArray(containerIds) ? containerIds : [containerIds]).forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = html;
        });
    } catch (e) { console.error('[AgentState] error:', e); }
}

function clearAgentState(containerIds) {
    const empty = '<p class="text-sm text-gray-400 dark:text-gray-500 italic">No state yet.</p>';
    (Array.isArray(containerIds) ? containerIds : [containerIds]).forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = empty;
    });
}
