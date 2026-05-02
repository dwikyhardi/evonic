/**
 * transport.js — SSEAdapter, PollingAdapter, ReplayAdapter.
 *
 * All three share the same interface:
 *   start(handler)   // calls handler({ event, data, seq }) for each TurnEvent
 *   stop()
 */

import { log } from './debug.js';

// ── SSEAdapter ────────────────────────────────────────────────────────────────

const SSE_EVENTS = [
    'turn_begin', 'turn_split', 'thinking', 'tool_call_started', 'tool_executed',
    'response_chunk', 'done', 'approval_required', 'approval_resolved', 'retry',
    'message_injected', 'message_injection_applied', 'session_clear',
];

export class SSEAdapter {
    /**
     * @param {string} url         - SSE stream URL
     * @param {object} [opts]
     * @param {string} [opts.agentId]
     * @param {string} [opts.sessionId]
     * @param {number} [opts.afterSeq=0]  - resume from this seq (gap-fill will request from here)
     */
    constructor(url, opts = {}) {
        this._url = url;
        this._agentId = opts.agentId || '';
        this._sessionId = opts.sessionId || (new URL(url, window.location.origin).searchParams.get('session_id') || '');
        this._lastSeq = opts.afterSeq || 0;
        this._handler = null;
        this._es = null;
        this._fillingGap = false;
        this._pendingQueue = [];
        this._log = log('sse');
    }

    start(handler) {
        this._handler = handler;
        this._intentionallyStopped = false;
        this._connect(this._url);
    }

    stop() {
        this._intentionallyStopped = true;
        if (this._es) {
            this._es.close();
            this._es = null;
        }
    }

    _connect(url) {
        this._log.info('open', url);
        const es = new EventSource(url);
        this._es = es;

        for (const evtName of SSE_EVENTS) {
            es.addEventListener(evtName, (e) => {
                let data;
                try { data = JSON.parse(e.data); } catch (err) { data = {}; }
                this._log.debug('event', evtName, 'seq', data.seq, 'size', e.data.length);
                this._handleRaw(evtName, data);
            });
        }

        es.onerror = () => {
            this._log.warn('SSE error/closed', url);
            es.close();
            if (this._es === es) this._es = null;
            // Only reconnect if this was NOT an intentional stop (e.g. after 'done')
            if (this._intentionallyStopped) {
                this._log.info('intentionally stopped — no reconnect');
                return;
            }
            setTimeout(() => {
                if (this._intentionallyStopped) return;
                if (this._es) return; // another stream already started
                const u = new URL(url, window.location.origin);
                if (this._lastSeq > 0) u.searchParams.set('after', this._lastSeq);
                const resumeUrl = u.pathname + u.search;
                this._log.info('reconnecting from seq', this._lastSeq, resumeUrl);
                this._connect(resumeUrl);
            }, 2000);
        };
    }

    _handleRaw(evtName, data) {
        const seq = data.seq || 0;

        if (this._fillingGap) {
            this._pendingQueue.push({ evtName, data });
            return;
        }

        if (seq && this._lastSeq > 0 && seq > this._lastSeq + 1) {
            this._log.warn('seq gap detected', this._lastSeq, '→', seq, '— filling');
            this._fillingGap = true;
            this._pendingQueue.push({ evtName, data });
            this._fillGap(this._lastSeq, seq).then(() => {
                this._fillingGap = false;
                while (this._pendingQueue.length > 0) {
                    const item = this._pendingQueue.shift();
                    const itemSeq = item.data.seq || 0;
                    if (itemSeq && itemSeq <= this._lastSeq) continue;
                    if (itemSeq) this._lastSeq = itemSeq;
                    this._dispatch(item.evtName, item.data);
                }
            });
            return;
        }

        if (seq) this._lastSeq = seq;
        this._dispatch(evtName, data);
    }

    async _fillGap(afterSeq, upToSeq) {
        try {
            const agentId = this._agentId || this._url.match(/\/agents\/([^/?]+)\//)?.[1] || '';
            const res = await $.getJSON(
                `/api/agents/${encodeURIComponent(agentId)}/chat/events?session_id=${encodeURIComponent(this._sessionId)}&after=${afterSeq}&up_to=${upToSeq}`
            );
            for (const ev of (res.events || [])) {
                if (ev.seq <= this._lastSeq) continue;
                this._lastSeq = ev.seq;
                this._dispatch(ev.event, ev.data);
            }
        } catch (err) {
            this._log.warn('gap-fill failed', err, '— skipping gap');
            this._lastSeq = upToSeq - 1;
        }
    }

    _dispatch(evtName, data) {
        if (evtName === 'session_clear') {
            this._handler({ event: 'session_clear', data, seq: data.seq || 0 });
            return;
        }
        // done: stop reconnecting after this
        if (evtName === 'done') {
            this._handler({ event: 'done', data, seq: data.seq || 0 });
            this.stop();
            return;
        }
        this._handler({ event: evtName, data, seq: data.seq || 0 });
    }
}

// ── PollingAdapter ────────────────────────────────────────────────────────────

/**
 * Polls the JSONL history endpoint for new entries, converts them to TurnEvents.
 * Useful as a fallback when SSE fails or for initial replay.
 */
export class PollingAdapter {
    /**
     * @param {string} baseUrl     - e.g. `/api/agents/${id}/chat`
     * @param {object} opts
     * @param {string} [opts.sessionId]
     * @param {number} [opts.intervalMs=1000]
     * @param {number} [opts.startTs=0]       - only fetch entries newer than this ts
     */
    constructor(baseUrl, opts = {}) {
        this._baseUrl = baseUrl;
        this._sessionId = opts.sessionId || '';
        this._intervalMs = opts.intervalMs || 1000;
        this._lastTs = opts.startTs || 0;
        this._handler = null;
        this._timer = null;
        this._running = false;
        this._log = log('poll');
    }

    start(handler) {
        this._handler = handler;
        this._running = true;
        this._timer = setInterval(() => this._tick(), this._intervalMs);
        this._log.info('polling started', this._baseUrl);
    }

    stop() {
        this._running = false;
        if (this._timer) { clearInterval(this._timer); this._timer = null; }
        this._log.info('polling stopped');
    }

    async _tick() {
        if (!this._running) return;
        try {
            const qs = this._sessionId
                ? `session_id=${encodeURIComponent(this._sessionId)}&after_ts=${this._lastTs}&limit=50`
                : `user_id=web_test&after_ts=${this._lastTs}&limit=50`;
            const data = await $.getJSON(`${this._baseUrl}?${qs}`);
            const entries = data.entries || [];
            this._log.debug('tick delta', entries.length, 'lastTs', this._lastTs);
            if (!entries.length) return;

            for (const entry of entries) {
                if (entry.ts <= this._lastTs) continue;
                this._lastTs = entry.ts;

                // Convert JSONL entry to TurnEvent
                const evt = this._entryToEvent(entry);
                if (evt) {
                    // Progressive: one event per rAF to avoid dumping all at once
                    await new Promise(r => requestAnimationFrame(r));
                    this._handler(evt);
                }
            }
        } catch (e) {
            this._log.warn('poll tick error', e);
        }
    }

    _entryToEvent(entry) {
        if (entry.type === 'final') {
            return { event: 'done', data: { thinking_duration: (entry.metadata || {}).thinking_duration }, seq: 0, _entry: entry };
        }
        if (entry.type === 'error') {
            return { event: 'done', data: { thinking_duration: null, error: true }, seq: 0, _entry: entry };
        }
        if (entry.type === 'thinking') {
            return { event: 'thinking', data: { content: entry.content }, seq: 0 };
        }
        if (entry.type === 'tool_call') {
            return { event: 'tool_call_started', data: { tool: entry.function, args: entry.params || {}, param_types: {} }, seq: 0 };
        }
        if (entry.type === 'tool_output') {
            let result;
            try { result = JSON.parse(entry.content); } catch (e) { result = { data: entry.content }; }
            return { event: 'tool_executed', data: { tool: entry.function, result, error: !!entry.error }, seq: 0 };
        }
        if (entry.type === 'intermediate') {
            return { event: 'response_chunk', data: { content: entry.content, is_final: false }, seq: 0 };
        }
        return null;
    }
}

// ── ReplayAdapter ─────────────────────────────────────────────────────────────

/**
 * Emits events from a static history array.
 * batch:true → synchronous (instant render of finalized turns).
 * batch:false → one event per rAF (progressive animation).
 */
export class ReplayAdapter {
    /**
     * @param {Array} events  - array of { event, data, seq } objects
     * @param {object} [opts]
     * @param {boolean} [opts.batch=true]
     */
    constructor(events, opts = {}) {
        this._events = events;
        this._batch = opts.batch !== false;
        this._handler = null;
        this._stopped = false;
        this._log = log('replay');
    }

    start(handler) {
        this._handler = handler;
        if (this._batch) {
            for (const evt of this._events) {
                if (this._stopped) break;
                handler(evt);
            }
        } else {
            this._playAsync();
        }
    }

    stop() {
        this._stopped = true;
    }

    async _playAsync() {
        for (const evt of this._events) {
            if (this._stopped) break;
            await new Promise(r => requestAnimationFrame(r));
            this._handler(evt);
        }
    }
}
