/**
 * Users dashboard frontend (jQuery).
 *
 * Two pages share this module:
 *   - /users          → list + new-user modal      (initListPage)
 *   - /users/<id>     → user detail + identities   (initDetailPage)
 *
 * All endpoints sit behind the existing auth gate in app.py.
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
        // Lightweight inline notification (no dep on any toast lib).
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

    // =====================================================================
    //  /users   — list + new-user modal
    // =====================================================================

    function renderUsersGrid(users) {
        var $grid = $('#users-grid');
        var $empty = $('#users-empty');
        $grid.empty();
        if (!users.length) {
            $empty.removeClass('hidden');
            return;
        }
        $empty.addClass('hidden');
        users.forEach(function (u) {
            var enabled = u.enabled === 1 || u.enabled === true;
            var card = ''
                + '<a href="/users/' + esc(u.id) + '" class="block bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 hover:border-indigo-400 hover:shadow-md transition">'
                +   '<div class="flex items-start justify-between gap-2 mb-2">'
                +     '<div class="font-semibold text-gray-800 dark:text-gray-100 truncate">' + esc(u.name) + '</div>'
                +     '<span class="text-xs px-2 py-0.5 rounded ' + (enabled ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-300') + '">'
                +       (enabled ? 'enabled' : 'disabled')
                +     '</span>'
                +   '</div>'
                +   (u.note ? '<div class="text-xs text-gray-500 dark:text-gray-400 mb-2 line-clamp-2">' + esc(u.note) + '</div>' : '')
                +   '<div class="text-xs text-gray-400">' + (u.identity_count || 0) + ' identit' + ((u.identity_count === 1) ? 'y' : 'ies') + '</div>'
                + '</a>';
            $grid.append(card);
        });
    }

    function loadUsers(search) {
        return ajaxJson('GET', '/api/users' + (search ? '?search=' + encodeURIComponent(search) : ''))
            .done(function (data) { renderUsersGrid(data.users || []); })
            .fail(function (xhr) { toast(errorMessage(xhr, 'Failed to load users'), 'error'); });
    }

    function openNewUserModal() {
        $('#new-user-name').val('');
        $('#new-user-note').val('');
        $('#new-user-error').addClass('hidden').text('');
        $('#new-user-modal').removeClass('hidden');
        setTimeout(function () { $('#new-user-name').focus(); }, 50);
    }

    function closeNewUserModal() {
        $('#new-user-modal').addClass('hidden');
    }

    function submitNewUser() {
        var name = ($('#new-user-name').val() || '').trim();
        var note = ($('#new-user-note').val() || '').trim() || null;
        if (!name) {
            $('#new-user-error').removeClass('hidden').text('Name is required.');
            return;
        }
        ajaxJson('POST', '/api/users', { name: name, note: note })
            .done(function (data) {
                closeNewUserModal();
                if (data && data.id) {
                    window.location.href = '/users/' + data.id;
                } else {
                    loadUsers();
                }
            })
            .fail(function (xhr) {
                $('#new-user-error').removeClass('hidden').text(errorMessage(xhr, 'Failed to create user'));
            });
    }

    function initListPage() {
        var t = null;
        $('#user-search').on('input', function () {
            clearTimeout(t);
            var v = this.value;
            t = setTimeout(function () { loadUsers(v); }, 200);
        });
        $('#btn-new-user').on('click', openNewUserModal);
        $('#btn-new-user-cancel, #new-user-backdrop').on('click', closeNewUserModal);
        $('#btn-new-user-save').on('click', submitNewUser);
        $('#new-user-name, #new-user-note').on('keydown', function (e) {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitNewUser();
        });
        loadUsers();
    }

    // =====================================================================
    //  /users/<id>   — detail page + identities
    // =====================================================================

    var DETAIL_STATE = {
        userId: null,
        channels: [],
        agents: [],
    };

    function loadAgents() {
        return ajaxJson('GET', '/api/agents').then(function (data) {
            DETAIL_STATE.agents = (data && data.agents) || [];
        });
    }

    function loadChannels() {
        return ajaxJson('GET', '/api/channels').then(function (data) {
            DETAIL_STATE.channels = (data && data.channels) || [];
        });
    }

    function loadUser() {
        return ajaxJson('GET', '/api/users/' + DETAIL_STATE.userId).then(function (data) {
            applyUser(data.user || {});
            renderIdentities(data.identities || []);
        });
    }

    function applyUser(user) {
        $('#ud-name-display').text(user.name || '');
        $('#ud-breadcrumb-name').text(user.name || '');
        $('#ud-name').val(user.name || '');
        $('#ud-note').val(user.note || '');
        $('#ud-enabled').prop('checked', user.enabled === 1 || user.enabled === true);
    }

    function saveUser() {
        var payload = {
            name: ($('#ud-name').val() || '').trim(),
            note: ($('#ud-note').val() || '').trim() || null,
            enabled: $('#ud-enabled').is(':checked')
        };
        if (!payload.name) {
            $('#ud-save-status').text('Name is required.').css('color', '#ef4444');
            return;
        }
        $('#ud-save-status').text('Saving...').css('color', '');
        ajaxJson('PUT', '/api/users/' + DETAIL_STATE.userId, payload)
            .done(function (data) {
                applyUser(data.user || {});
                $('#ud-save-status').text('Saved.').css('color', '#059669');
                setTimeout(function () { $('#ud-save-status').text(''); }, 1500);
            })
            .fail(function (xhr) {
                $('#ud-save-status').text(errorMessage(xhr, 'Save failed')).css('color', '#ef4444');
            });
    }

    function deleteUser() {
        if (!window.confirm('Delete this user and all their channel identities?')) return;
        ajaxJson('DELETE', '/api/users/' + DETAIL_STATE.userId)
            .done(function () {
                window.location.href = '/users';
            })
            .fail(function (xhr) { toast(errorMessage(xhr, 'Delete failed'), 'error'); });
    }

    function renderIdentities(idents) {
        var $list = $('#ud-identities');
        var $empty = $('#ud-identities-empty');
        $list.empty();
        if (!idents.length) {
            $empty.removeClass('hidden');
            return;
        }
        $empty.addClass('hidden');

        idents.forEach(function (i) {
            var enabled = i.enabled === 1 || i.enabled === true;
            var agentOptions = '<option value="">-- no agent (disabled) --</option>';
            DETAIL_STATE.agents.forEach(function (a) {
                var sel = a.id === i.agent_id ? 'selected' : '';
                agentOptions += '<option value="' + esc(a.id) + '" ' + sel + '>' + esc(a.name || a.id) + '</option>';
            });

            var channelLabel = (i.channel_name || '(unnamed)') + ' · ' + (i.channel_type || '?');
            var row = ''
                + '<div class="border border-gray-200 dark:border-gray-700 rounded-lg p-3 flex flex-wrap items-center gap-3" data-identity-id="' + esc(i.id) + '">'
                +   '<div class="flex-1 min-w-[160px]">'
                +     '<div class="text-xs text-gray-400 mb-1">Channel</div>'
                +     '<div class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate" title="' + esc(i.channel_id) + '">' + esc(channelLabel) + '</div>'
                +   '</div>'
                +   '<div class="flex-1 min-w-[140px]">'
                +     '<div class="text-xs text-gray-400 mb-1">External ID</div>'
                +     '<input type="text" class="ud-i-ext w-full p-1.5 border border-gray-300 dark:border-gray-600 rounded text-sm bg-white dark:bg-gray-900 dark:text-gray-100" value="' + esc(i.external_user_id) + '">'
                +   '</div>'
                +   '<div class="flex-1 min-w-[180px]">'
                +     '<div class="text-xs text-gray-400 mb-1">Routed Agent</div>'
                +     '<select class="ud-i-agent w-full p-1.5 border border-gray-300 dark:border-gray-600 rounded text-sm bg-white dark:bg-gray-900 dark:text-gray-100">' + agentOptions + '</select>'
                +   '</div>'
                +   '<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 cursor-pointer">'
                +     '<input type="checkbox" class="ud-i-enabled rounded border-gray-300" ' + (enabled ? 'checked' : '') + '>'
                +     '<span>Enabled</span>'
                +   '</label>'
                +   '<button class="ud-i-save px-3 py-1.5 bg-indigo-500 hover:bg-indigo-600 text-white rounded text-sm font-medium">Save</button>'
                +   '<button class="ud-i-delete px-3 py-1.5 text-red-600 border border-red-200 rounded text-sm hover:bg-red-50 dark:hover:bg-red-900/20">Delete</button>'
                + '</div>';
            $list.append(row);
        });
    }

    function saveIdentity($row) {
        var iid = $row.data('identity-id');
        var payload = {
            external_user_id: ($row.find('.ud-i-ext').val() || '').trim(),
            agent_id: $row.find('.ud-i-agent').val() || null,
            enabled: $row.find('.ud-i-enabled').is(':checked')
        };
        ajaxJson('PUT', '/api/identities/' + iid, payload)
            .done(function () { toast('Identity saved'); })
            .fail(function (xhr) { toast(errorMessage(xhr, 'Save failed'), 'error'); });
    }

    function deleteIdentity($row) {
        if (!window.confirm('Delete this identity?')) return;
        var iid = $row.data('identity-id');
        ajaxJson('DELETE', '/api/identities/' + iid)
            .done(function () { loadUser(); })
            .fail(function (xhr) { toast(errorMessage(xhr, 'Delete failed'), 'error'); });
    }

    function openAddIdentityModal() {
        var $ch = $('#ai-channel').empty();
        var hasChannels = DETAIL_STATE.channels && DETAIL_STATE.channels.length > 0;
        if (hasChannels) {
            $ch.append('<option value="">-- pick a channel --</option>');
            DETAIL_STATE.channels.forEach(function (c) {
                $ch.append('<option value="' + esc(c.id) + '">' + esc((c.name || '(unnamed)') + ' · ' + (c.type || '?') + ' (agent: ' + (c.agent_name || '-') + ')') + '</option>');
            });
            $ch.prop('disabled', false);
            $('#btn-ai-save').prop('disabled', false).removeClass('opacity-50 cursor-not-allowed');
            $('#ai-no-channels-hint').addClass('hidden');
        } else {
            $ch.append('<option value="">-- no channels available --</option>');
            $ch.prop('disabled', true);
            $('#btn-ai-save').prop('disabled', true).addClass('opacity-50 cursor-not-allowed');
            // Show inline hint with a deep-link to the Agents page (where channels are created)
            var $hint = $('#ai-no-channels-hint');
            if ($hint.length === 0) {
                $hint = $('<div id="ai-no-channels-hint" class="mt-2 text-xs text-amber-600 dark:text-amber-400"></div>');
                $('#ai-channel').after($hint);
            }
            $hint
                .removeClass('hidden')
                .html('No channels are configured yet. Create a channel first from <a href="/agents" class="underline font-medium">Agents</a> → open an agent → <em>Add Channel</em>.');
        }
        var $ag = $('#ai-agent').empty().append('<option value="">-- no agent (disabled) --</option>');
        DETAIL_STATE.agents.forEach(function (a) {
            $ag.append('<option value="' + esc(a.id) + '">' + esc(a.name || a.id) + '</option>');
        });
        $('#ai-external-id').val('');
        $('#ai-enabled').prop('checked', true);
        $('#ai-error').addClass('hidden').text('');
        $('#add-identity-modal').removeClass('hidden');
    }

    function closeAddIdentityModal() {
        $('#add-identity-modal').addClass('hidden');
    }

    function submitNewIdentity() {
        var payload = {
            channel_id: ($('#ai-channel').val() || '').trim(),
            external_user_id: ($('#ai-external-id').val() || '').trim(),
            agent_id: $('#ai-agent').val() || null,
            enabled: $('#ai-enabled').is(':checked')
        };
        if (!payload.channel_id || !payload.external_user_id) {
            $('#ai-error').removeClass('hidden').text('Channel and external user ID are required.');
            return;
        }
        ajaxJson('POST', '/api/users/' + DETAIL_STATE.userId + '/identities', payload)
            .done(function () {
                closeAddIdentityModal();
                loadUser();
            })
            .fail(function (xhr) {
                $('#ai-error').removeClass('hidden').text(errorMessage(xhr, 'Create failed'));
            });
    }

    function initDetailPage(userId) {
        DETAIL_STATE.userId = userId;
        $('#ud-save').on('click', saveUser);
        $('#ud-delete').on('click', deleteUser);
        $('#ud-enabled').on('change', saveUser);
        $('#ud-add-identity').on('click', openAddIdentityModal);
        $('#btn-ai-cancel, #add-identity-backdrop').on('click', closeAddIdentityModal);
        $('#btn-ai-save').on('click', submitNewIdentity);

        // Identity row event delegation
        $('#ud-identities').on('click', '.ud-i-save', function () {
            saveIdentity($(this).closest('[data-identity-id]'));
        });
        $('#ud-identities').on('click', '.ud-i-delete', function () {
            deleteIdentity($(this).closest('[data-identity-id]'));
        });
        $('#ud-identities').on('change', '.ud-i-enabled', function () {
            saveIdentity($(this).closest('[data-identity-id]'));
        });

        $.when(loadAgents(), loadChannels()).always(loadUser);
    }

    // ---------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------
    window.EvonicUsers = {
        initListPage: initListPage,
        initDetailPage: initDetailPage
    };

})(window, jQuery);
