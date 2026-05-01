"""
Authentication Blueprint — admin login with Cloudflare Turnstile captcha.
"""

import functools
import requests
from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify
import config

auth_bp = Blueprint('auth', __name__)


def login_required(f):
    """Decorator that enforces authentication."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if session.get('authenticated'):
            return f(*args, **kwargs)
        # API requests get 401, page requests get redirected
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Authentication required'}), 401
        return redirect(url_for('auth.login_page', next=request.path))
    return decorated


@auth_bp.route('/login', methods=['GET'])
def login_page():
    if session.get('authenticated'):
        return redirect(request.args.get('next', '/'))
    return render_template('login.html',
                           turnstile_site_key=config.TURNSTILE_SITE_KEY,
                           error=None)


@auth_bp.route('/login', methods=['POST'])
def login_submit():
    password = request.form.get('password', '')
    turnstile_token = request.form.get('cf-turnstile-response', '')
    next_url = request.form.get('next', '/')

    # Verify Turnstile if configured
    if config.TURNSTILE_SECRET_KEY:
        try:
            ts_res = requests.post(
                'https://challenges.cloudflare.com/turnstile/v0/siteverify',
                data={
                    'secret': config.TURNSTILE_SECRET_KEY,
                    'response': turnstile_token,
                    'remoteip': request.remote_addr,
                },
                timeout=10
            )
            ts_data = ts_res.json()
            if not ts_data.get('success'):
                return render_template('login.html',
                                       turnstile_site_key=config.TURNSTILE_SITE_KEY,
                                       error='Captcha verification failed. Please try again.')
        except Exception:
            return render_template('login.html',
                                   turnstile_site_key=config.TURNSTILE_SITE_KEY,
                                   error='Captcha verification error. Please try again.')

    if not config.ADMIN_PASSWORD_HASH:
        return render_template('login.html',
                               turnstile_site_key=config.TURNSTILE_SITE_KEY,
                               error='Admin password not configured.')

    from werkzeug.security import check_password_hash
    if not check_password_hash(config.ADMIN_PASSWORD_HASH, password):
        return render_template('login.html',
                               turnstile_site_key=config.TURNSTILE_SITE_KEY,
                               error='Invalid password.')

    session['authenticated'] = True
    return redirect(next_url)


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login_page'))
