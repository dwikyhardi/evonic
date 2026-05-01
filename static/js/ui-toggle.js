/**
 * mkToggle — returns an HTML string for a standalone toggle switch.
 *
 * All visual behaviour (colour, knob, transitions) is handled by the
 * `.dyn-toggle` CSS class defined in style.css — no Tailwind compound
 * variants are needed, so this works correctly in dynamically-inserted HTML.
 *
 * @param {object}  opts
 * @param {boolean} [opts.checked=false]    Initial checked state
 * @param {string}  [opts.onChange='']      JS expression for onchange handler
 *                                          e.g. "toggleFoo('id', this.checked)"
 * @param {string}  [opts.id='']            Optional id for the <input>
 * @param {boolean} [opts.disabled=false]   Disabled state
 * @param {string}  [opts.extraClass='']    Extra classes appended to the <label>
 * @returns {string} HTML string — a <label> containing the toggle
 */
function mkToggle({ checked = false, onChange = '', id = '', disabled = false, extraClass = '' } = {}) {
    const idAttr  = id       ? ` id="${id}"`             : '';
    const chkAttr = checked  ? ' checked'                : '';
    const disAttr = disabled ? ' disabled'               : '';
    const chgAttr = onChange ? ` onchange="${onChange}"` : '';
    const cls     = 'relative inline-flex items-center cursor-pointer' + (extraClass ? ' ' + extraClass : '');
    return `<label class="${cls}"><input type="checkbox"${idAttr}${chkAttr}${disAttr}${chgAttr} class="sr-only peer"><span class="dyn-toggle"></span></label>`;
}
