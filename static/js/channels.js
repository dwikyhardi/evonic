/**
 * Channels dashboard frontend (jQuery).
 *
 * Drives `/channels` — list, search, create/edit modal, start/stop/restart.
 * Mirrors the visual + interaction patterns of `users.js` so the two pages
 * feel consistent.
 */
(function (window, $) {
    'use strict';

    // ---------------------------------------------------------------------
    // Shared helpers
    // ---------------------------------------------------------------------

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function toast(msg, kind) {
        var bg = kind === 'error' ? 'bg-red-500' : (kind === 'warn' ? 'bg-amber-500' : 'bg-gray-800');
        var $t = $('<div></div>')
            .addClass('fixed bottom-6 right-6 z-[60] text-white px-4 py-2 rounded-lg shadow-lg text-sm')
            .addClass(bg)
            .text(msg);
        $('body').append($t);
        setTimeout(function () { $t.fadeOut(300, function () { $t.remove(); }); }, 2200);
    }

    function ajaxJson(method, url, body) {
        return $.ajax({
            url: url,
            method: method,
            contentType: 'application/json',
            data: body == null ? undefined : JSON.stringify(body),
            dataType: 'json'
        });
    }

    function errorMessage(jqXHR, fallback) {
        try {
            var j = jqXHR.responseJSON;
            if (j && j.error) return j.error;
        } catch (e) {}
        return fallback || 'Request failed';
    }

    // ---------------------------------------------------------------------
    // Type-specific config schema (forward-compat: add Discord/Slack here).
    // ---------------------------------------------------------------------

    var CONFIG_SCHEMA = {
        telegram: [
            { key: 'bot_token', label: 'Bot token', type: 'password', required: true,
              hint: 'Get one from @BotFather on Telegram.' }
        ]
    };

    function renderConfigFields(type, config) {
        var $box = $('#channel-config-fields').empty();
        var fields = CONFIG_SCHEMA[type] || [];
        config = config || {};
        fields.forEach(function (f) {
            var val = config[f.key] != null ? String(config[f.key]) : '';
            var html = ''
                + '<div class="mb-3">'
                +   '<label class="block mb-1 text-gray-700 dark:text-gray-300 text-sm font-medium">'
                +     esc(f.label) + (f.required ? ' *' : '')
                +   '</label>'
                +   '<input type="' + (f.type === 'password' ? 'password' : 'text') + '"'
                +     ' data-config-key="' + esc(f.key) + '"'
                +     ' value="' + esc(val) + '"'
                +     ' class="w-full p-2.5 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-900 dark:text-gray-100 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/10">'
                +   (f.hint ? '<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">' + esc(f.hint) + '</p>' : '')
                + '</div>';
            $box.append(html);
        });
    }

    function readConfigFromForm() {
        var cfg = {};
        $('#channel-config-fields [data-config-key]').each(function () {
            var k = $(this).data('config-key');
            var v = ($(this).val() || '').trim();
            if (v !== '') cfg[k] = v;
        });
        return cfg;
    }

    // ---------------------------------------------------------------------
    // List rendering
    // ---------------------------------------------------------------------

    var STATE = { channels: [], agents: [], filter: '', editingId: null, deletingId: null };

    function renderGrid() {
        var $grid = $('#channels-grid');
        var $empty = $('#channels-empty');
        var q = (STATE.filter || '').toLowerCase();
        var rows = STATE.channels.filter(function (c) {
            if (!q) return true;
            return (c.name || '').toLowerCase().indexOf(q) >= 0
                || (c.type || '').toLowerCase().indexOf(q) >= 0
                || (c.agent_name || '').toLowerCase().indexOf(q) >= 0;
        });
        $grid.empty();
        if (!rows.length) { $empty.removeClass('hidden'); return; }
        $empty.addClass('hidden');
        rows.forEach(function (c) {
            var enabled = c.enabled === 1 || c.enabled === true;
            var running = c.running === true;
            var statusClass = running
                ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-300';
            var agentLink = c.agent_id
                ? '<a href="/agents/' + esc(c.agent_id) + '" class="text-indigo-500 hover:underline">' + esc(c.agent_name || c.agent_id) + '</a>'
                : '<span class="text-amber-600">(missing)</span>';
            var lifecycleBtn = running
                ? '<button data-act="stop" data-id="' + esc(c.id) + '" class="text-xs px-2.5 py-1 rounded border border-amber-300 text-amber-700 hover:bg-amber-50">Stop</button>'
                : '<button data-act="start" data-id="' + esc(c.id) + '" class="text-xs px-2.5 py-1 rounded border border-green-300 text-green-700 hover:bg-green-50"' + (enabled ? '' : ' disabled') + '>Start</button>';
            var card = ''
                + '<div class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 flex flex-col gap-2">'
                +   '<div class="flex items-start justify-between gap-2">'
                +     '<div class="min-w-0 flex-1">'
                +       '<div class="font-semibold text-gray-800 dark:text-gray-100 truncate">' + esc(c.name || '(unnamed)') + '</div>'
                +       '<div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">' + esc(c.type || '?') + '</div>'
                +     '</div>'
                +     '<span class="text-xs px-2 py-0.5 rounded ' + statusClass + '">' + (running ? 'running' : 'stopped') + '</span>'
                +   '</div>'
                +   '<div class="text-xs text-gray-500 dark:text-gray-400">Default agent: ' + agentLink + '</div>'
                +   '<div class="flex flex-wrap gap-2 pt-1">'
                +     '<button data-act="edit" data-id="' + esc(c.id) + '" class="text-xs px-2.5 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700">Edit</button>'
                +     lifecycleBtn
                +     '<button data-act="restart" data-id="' + esc(c.id) + '" class="text-xs px-2.5 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700">Restart</button>'
                +     '<button data-act="delete" data-id="' + esc(c.id) + '" class="text-xs px-2.5 py-1 rounded border border-red-300 text-red-700 hover:bg-red-50 ml-auto">Delete</button>'
                +   '</div>'
                + '</div>';
            $grid.append(card);
        });
    }

    function loadAll() {
        return $.when(
            ajaxJson('GET', '/api/channels'),
            ajaxJson('GET', '/api/agents')
        ).done(function (chRes, agRes) {
            STATE.channels = (chRes[0] && chRes[0].channels) || [];
            STATE.agents = (agRes[0] && agRes[0].agents) || [];
            renderGrid();
        }).fail(function (xhr) {
            toast(errorMessage(xhr, 'Failed to load channels'), 'error');
        });
    }

    // ---------------------------------------------------------------------
    // Modal: create / edit
    // ---------------------------------------------------------------------

    function populateAgentPicker(selectedId) {
        var $sel = $('#channel-agent').empty();
        $sel.append('<option value="">-- pick an agent --</option>');
        STATE.agents.forEach(function (a) {
            var s = a.id === selectedId ? ' selected' : '';
            $sel.append('<option value="' + esc(a.id) + '"' + s + '>' + esc(a.name || a.id) + '</option>');
        });
    }

    function openCreateModal() {
        STATE.editingId = null;
        $('#channel-modal-title').text('New Channel');
        $('#channel-type').val('telegram').prop('disabled', false);
        $('#channel-name').val('');
        $('#channel-enabled').prop('checked', true);
        renderConfigFields('telegram', {});
        populateAgentPicker(null);
        $('#channel-modal-error').addClass('hidden').text('');
        $('#channel-modal').removeClass('hidden');
        setTimeout(function () { $('#channel-name').focus(); }, 50);
    }

    function openEditModal(channelId) {
        var c = STATE.channels.find(function (x) { return x.id === channelId; });
        if (!c) return;
        STATE.editingId = channelId;
        $('#channel-modal-title').text('Edit Channel');
        $('#channel-type').val(c.type || 'telegram').prop('disabled', true);
        $('#channel-name').val(c.name || '');
        $('#channel-enabled').prop('checked', c.enabled === 1 || c.enabled === true);
        renderConfigFields(c.type, c.config || {});
        populateAgentPicker(c.agent_id);
        $('#channel-modal-error').addClass('hidden').text('');
        $('#channel-modal').removeClass('hidden');
    }

    function closeModal() {
        $('#channel-modal').addClass('hidden');
        STATE.editingId = null;
    }

    function submitModal() {
        var $err = $('#channel-modal-error').addClass('hidden').text('');
        var payload = {
            type: $('#channel-type').val(),
            name: ($('#channel-name').val() || '').trim(),
            agent_id: $('#channel-agent').val(),
            config: readConfigFromForm(),
            enabled: $('#channel-enabled').is(':checked')
        };
        if (!payload.name) { $err.removeClass('hidden').text('Name is required.'); return; }
        if (!payload.agent_id) { $err.removeClass('hidden').text('Default agent is required.'); return; }

        if (STATE.editingId) {
            // Don't send `type` on edit (it's locked).
            var put = { name: payload.name, agent_id: payload.agent_id, config: payload.config, enabled: payload.enabled };
            ajaxJson('PUT', '/api/channels/' + encodeURIComponent(STATE.editingId), put)
                .done(function () { closeModal(); toast('Channel saved'); loadAll(); })
                .fail(function (xhr) { $err.removeClass('hidden').text(errorMessage(xhr, 'Save failed')); });
        } else {
            ajaxJson('POST', '/api/channels', payload)
                .done(function () { closeModal(); toast('Channel created'); loadAll(); })
                .fail(function (xhr) { $err.removeClass('hidden').text(errorMessage(xhr, 'Create failed')); });
        }
    }

    // ---------------------------------------------------------------------
    // Row actions
    // ---------------------------------------------------------------------

    function actStart(id) {
        ajaxJson('POST', '/api/channels/' + encodeURIComponent(id) + '/start')
            .done(function () { toast('Started'); loadAll(); })
            .fail(function (xhr) { toast(errorMessage(xhr, 'Start failed'), 'error'); });
    }
    function actStop(id) {
        ajaxJson('POST', '/api/channels/' + encodeURIComponent(id) + '/stop')
            .done(function () { toast('Stopped'); loadAll(); })
            .fail(function (xhr) { toast(errorMessage(xhr, 'Stop failed'), 'error'); });
    }
    function actRestart(id) {
        ajaxJson('POST', '/api/channels/' + encodeURIComponent(id) + '/restart')
            .done(function () { toast('Restarted'); loadAll(); })
            .fail(function (xhr) { toast(errorMessage(xhr, 'Restart failed'), 'error'); });
    }
    function openDeleteModal(id) {
        var c = STATE.channels.find(function (x) { return x.id === id; });
        STATE.deletingId = id;
        $('#channel-delete-name').text(c && c.name ? '"' + c.name + '"' : 'this channel');
        $('#channel-delete-modal').removeClass('hidden');
        setTimeout(function () { $('#btn-channel-delete-cancel').focus(); }, 50);
    }
    function closeDeleteModal() {
        $('#channel-delete-modal').addClass('hidden');
        STATE.deletingId = null;
    }
    function confirmDelete() {
        var id = STATE.deletingId;
        if (!id) { closeDeleteModal(); return; }
        var $btn = $('#btn-channel-delete-confirm').prop('disabled', true).text('Deleting…');
        ajaxJson('DELETE', '/api/channels/' + encodeURIComponent(id))
            .done(function () { closeDeleteModal(); toast('Deleted'); loadAll(); })
            .fail(function (xhr) { toast(errorMessage(xhr, 'Delete failed'), 'error'); closeDeleteModal(); })
            .always(function () { $btn.prop('disabled', false).text('Delete'); });
    }

    // ---------------------------------------------------------------------
    // Public init
    // ---------------------------------------------------------------------

    function init() {
        $('#btn-new-channel').on('click', openCreateModal);
        $('#btn-channel-cancel, #channel-modal-backdrop').on('click', closeModal);
        $('#btn-channel-save').on('click', submitModal);
        $('#btn-channel-delete-cancel, #channel-delete-modal-backdrop').on('click', closeDeleteModal);
        $('#btn-channel-delete-confirm').on('click', confirmDelete);
        // Esc key closes whichever modal is open.
        $(document).on('keydown.channelsModal', function (e) {
            if (e.key !== 'Escape') return;
            if (!$('#channel-delete-modal').hasClass('hidden')) closeDeleteModal();
            else if (!$('#channel-modal').hasClass('hidden')) closeModal();
        });
        $('#channel-type').on('change', function () {
            renderConfigFields($(this).val(), {});
        });
        $('#channel-search').on('input', function () {
            STATE.filter = ($(this).val() || '').trim();
            renderGrid();
        });
        $('#channels-grid').on('click', '[data-act]', function () {
            var id = $(this).data('id');
            switch ($(this).data('act')) {
                case 'edit':    openEditModal(id); break;
                case 'start':   actStart(id); break;
                case 'stop':    actStop(id); break;
                case 'restart': actRestart(id); break;
                case 'delete':  openDeleteModal(id); break;
            }
        });
        loadAll();
    }

    window.EvonicChannels = { init: init };

})(window, jQuery);
