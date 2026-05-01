with open('/workspace/plugins/kanban/templates/kanban.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Get the exact comment line
idx = content.find('Close on backdrop click')
line_start = content.rfind('\n', 0, idx) + 1
line_end = content.find('\n', idx)
comment_line = content[line_start:line_end]

old = '        });\n    }\n\n' + comment_line + '\n\n    $(\'#kb-modal\').on(\'click\', function(e) { if (e.target === this) closeModal(); });'

new = '''        });
    }

    // ── Agent Select Population ──

    let _agentCache = null;
    let _agentCacheTime = 0;

    function populateAgentSelect(selector, selectedValue) {
        const now = Date.now();
        if (!_agentCache || (now - _agentCacheTime) > 60000) {
            $.get('/api/agents', function(data) {
                _agentCache = (data.agents || []).map(a => a.id);
                _agentCacheTime = now;
                _doPopulateAgentSelect(selector, selectedValue);
            }).fail(function() {
                _agentCache = [];
                _agentCacheTime = now;
                _doPopulateAgentSelect(selector, selectedValue);
            });
        } else {
            _doPopulateAgentSelect(selector, selectedValue);
        }
    }

    function _doPopulateAgentSelect(selector, selectedValue) {
        const $sel = $(selector);
        const currentVal = $sel.val();
        $sel.find('option:not(:first)').remove();
        (_agentCache || []).forEach(function(agentId) {
            const opt = $('<option>').val(agentId).text(agentId);
            if (agentId === selectedValue || agentId === currentVal) {
                opt.prop('selected', true);
            }
            $sel.append(opt);
        });
    }

    ''' + comment_line + '''

    $('#kb-modal').on('click', function(e) { if (e.target === this) closeModal(); });'''

if old in content:
    content = content.replace(old, new, 1)
    with open('/workspace/plugins/kanban/templates/kanban.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS')
else:
    print('NOT FOUND')
    print('Looking for:')
    print(repr(old[:300]))
