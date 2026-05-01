/**
 * Toast Notification Module
 * Modular, reusable toast system using jQuery + Tailwind CSS
 * Usage: toast.show(message, type, duration)
 *   type: 'success' | 'error' | 'warning' | 'info'
 *   duration: ms (default 4000)
 */
(function($) {
    'use strict';

    // Configuration
    var config = {
        position: 'top-center',  // top-right | top-left | top-center | bottom-right | bottom-left
        maxToasts: 5,            // max toasts shown at once
        duration: 4000,          // default duration in ms
        animationDuration: 300,  // animation speed in ms
        gap: 12                  // gap between toasts in px
    };

    // Toast container
    var $container = null;

    // Initialize the toast system
    function init() {
        if ($container) return;

        // Create container
        var positionClasses = {
            'top-right': 'fixed top-4 right-4 z-[9999]',
            'top-left': 'fixed top-4 left-4 z-[9999]',
            'top-center': 'fixed top-4 left-1/2 -translate-x-1/2 z-[9999]',
            'bottom-right': 'fixed bottom-4 right-4 z-[9999]',
            'bottom-left': 'fixed bottom-4 left-4 z-[9999]'
        };

        $container = $('<div>')
            .addClass(positionClasses[config.position] || positionClasses['top-right'])
            .attr('id', 'toast-container')
            .css('display', 'flex')
            .css('flex-direction', 'column')
            .css('gap', config.gap + 'px');

        $('body').append($container);
    }

    // Get icon SVG based on type
    function getIcon(type) {
        var icons = {
            'success': '<svg class="w-5 h-5 text-white flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>',
            'error': '<svg class="w-5 h-5 text-white flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>',
            'warning': '<svg class="w-5 h-5 text-white flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>',
            'info': '<svg class="w-5 h-5 text-white flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>'
        };
        return icons[type] || icons['info'];
    }

    // Get style based on type
    function getStyle(type) {
        var styles = {
            'success': { bg: 'bg-green-500', icon: 'bg-green-600' },
            'error': { bg: 'bg-red-500', icon: 'bg-red-600' },
            'warning': { bg: 'bg-yellow-500', icon: 'bg-yellow-600' },
            'info': { bg: 'bg-blue-500', icon: 'bg-blue-600' }
        };
        return styles[type] || styles['info'];
    }

    // Show toast notification
    function show(message, type, duration) {
        type = type || 'info';
        duration = duration || config.duration;

        // Initialize if needed
        init();

        // Remove oldest if at max
        var $toasts = $container.children();
        if ($toasts.length >= config.maxToasts) {
            $toasts.first().fadeOut(config.animationDuration, function() {
                $(this).remove();
            });
        }

        // Create toast element
        var style = getStyle(type);
        var $toast = $('<div>')
            .addClass('flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg ' + style.bg)
            .css('max-width', '380px')
            .css('min-width', '250px')
            .css('cursor', 'pointer')
            .css('opacity', '0')
            .css('transform', config.position === 'top-center' ? 'translateY(-100%)' : 'translateX(100%)')
            .css('transition', 'opacity ' + config.animationDuration + 'ms ease, transform ' + config.animationDuration + 'ms ease');

        // Icon
        $toast.append(getIcon(type));

        // Message
        var $message = $('<div>')
            .addClass('text-white text-sm font-medium flex-1')
            .text(message);
        $toast.append($message);

        // Close button
        var $close = $('<button>')
            .addClass('text-white hover:text-gray-200 ml-2 flex-shrink-0')
            .html('&times;')
            .css('font-size', '18px')
            .css('line-height', '1')
            .css('padding', '0 4px');
        $toast.append($close);

        // Click to dismiss
        $toast.on('click', function(e) {
            if (!$(e.target).closest($close).length) {
                dismiss($toast);
            }
        });

        // Close button click
        $close.on('click', function(e) {
            e.stopPropagation();
            dismiss($toast);
        });

        // Add to container
        $container.append($toast);

        // Animate in
        setTimeout(function() {
            $toast.css('opacity', '1').css('transform', config.position === 'top-center' ? 'translateY(0)' : 'translateX(0)');
        }, 10);

        // Auto dismiss
        var timer = setTimeout(function() {
            dismiss($toast);
        }, duration);

        // Pause on hover
        $toast.on('mouseenter', function() {
            clearTimeout(timer);
        });

        $toast.on('mouseleave', function() {
            timer = setTimeout(function() {
                dismiss($toast);
            }, duration);
        });

        return $toast;
    }

    // Dismiss toast
    function dismiss($toast) {
        if (!$toast || $toast.data('dismissed')) return;
        $toast.data('dismissed', true);
        $toast.css('opacity', '0').css('transform', config.position === 'top-center' ? 'translateY(-100%)' : 'translateX(100%)');
        setTimeout(function() {
            $toast.remove();
        }, config.animationDuration);
    }

    // Convenience methods
    function success(message, duration) {
        return show(message, 'success', duration);
    }

    function error(message, duration) {
        return show(message, 'error', duration);
    }

    function warning(message, duration) {
        return show(message, 'warning', duration);
    }

    function info(message, duration) {
        return show(message, 'info', duration);
    }

    // Clear all toasts
    function clear() {
        if ($container) {
            $container.children().each(function() {
                dismiss($(this));
            });
        }
    }

    // Public API
    window.toast = {
        show: show,
        success: success,
        error: error,
        warning: warning,
        info: info,
        clear: clear,
        configure: function(newConfig) {
            $.extend(config, newConfig);
        }
    };

})(jQuery);
