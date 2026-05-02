/**
 * debug.js — namespaced logger, assertion helpers, window.__chatui diagnostic.
 *
 * Enable in DevTools:
 *   localStorage.setItem('debug', 'chat-ui:*')          // all namespaces
 *   localStorage.setItem('debug', 'chat-ui:turn,chat-ui:sse')  // selective
 */

const _getDebugSetting = () => {
    try { return localStorage.getItem('debug') || ''; } catch (e) { return ''; }
};

function _isEnabled(ns) {
    const setting = _getDebugSetting();
    if (!setting) return false;
    if (setting === '*' || setting === 'chat-ui:*') return true;
    return setting.split(',').some(s => {
        const t = s.trim();
        return t === 'chat-ui:' + ns || t === ns || t === 'chat-ui:*';
    });
}

/**
 * Returns a logger object for the given namespace.
 * warn and error always log; debug and info are gated by localStorage.
 */
export function log(ns) {
    const prefix = `[chat-ui:${ns}]`;
    return {
        debug: (...args) => { if (_isEnabled(ns)) console.debug(prefix, ...args); },
        info:  (...args) => { if (_isEnabled(ns)) console.info(prefix, ...args); },
        warn:  (...args) => console.warn(prefix, ...args),
        error: (...args) => console.error(prefix, ...args),
    };
}

export const DEV_MODE = !!_getDebugSetting();

/**
 * Asserts a condition. Logs an error always; throws in DEV_MODE.
 */
export function assert(cond, msg, context) {
    if (!cond) {
        log('assert').error('ASSERTION FAILED:', msg, context);
        if (DEV_MODE) throw new Error(`chat-ui assert: ${msg}`);
    }
}

/**
 * Install the window.__chatui diagnostic surface.
 * Called by index.js once the ChatUI instance is created.
 */
export function installDiagnostic(ui, activeTurns, eventLog) {
    if (!DEV_MODE) return;
    window.__chatui = {
        ui,
        turns: () => [...activeTurns.values()].map(t => ({
            id: t.id,
            phase: t.phase,
            anchor: t.$anchor && t.$anchor[0],
        })),
        history: () => [...eventLog],
        dump: () => {
            const rows = [...activeTurns.values()].map(t => ({
                id: t.id,
                phase: t.phase,
                seq: t._lastSeq,
            }));
            console.table(rows);
        },
    };
    log('debug').info('window.__chatui diagnostic installed');
}
