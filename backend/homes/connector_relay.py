"""
ConnectorRelay — manages WebSocket connections from Evonet connectors.

The WebSocket endpoint is served by Flask-Sock on the main app port:
  wss://<evonic-host>/ws/connector

The route in app.py calls connector_relay.handle_ws(ws, request) for each
incoming connection.  This module authenticates the token, wires up the
CloudHomeBackend, and runs the JSON-RPC message loop.
"""

import json
import logging
import datetime
import threading

_logger = logging.getLogger(__name__)


class ConnectorRelay:
    """
    Handles Evonet WebSocket connections on behalf of HomeManager.

    The Flask-Sock route calls handle_ws() for every connection.
    All active connections are tracked so HomeManager can query status.
    """

    def __init__(self):
        self._connections: dict[str, object] = {}   # home_id → ws
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Called by the Flask-Sock route in app.py
    # -------------------------------------------------------------------------

    def handle_ws(self, ws, flask_request) -> None:
        """Authenticate, register and run the message loop for one Evonet connection."""
        remote_addr = flask_request.headers.get('X-Forwarded-For') or flask_request.remote_addr or 'unknown'
        _logger.info("Evonet WebSocket handshake from %s", remote_addr)

        connector, home_id = self._authenticate(flask_request)
        if connector is None:
            auth_header = flask_request.headers.get('Authorization', '')
            if not auth_header:
                _logger.warning("Evonet rejected from %s: no Authorization header", remote_addr)
            else:
                token_preview = auth_header[7:15] + '...' if len(auth_header) > 14 else '(short)'
                _logger.warning("Evonet rejected from %s: invalid token %s", remote_addr, token_preview)
            return

        connector_id = connector['id']
        # Prefer live headers (sent on every connect) over stored values so
        # pre-configured binaries that skip the pair step still show device info.
        device_name = flask_request.headers.get('X-Device-Name', '').strip() or connector.get('device_name') or 'unknown'
        platform = flask_request.headers.get('X-Platform', '').strip() or connector.get('platform') or 'unknown'
        version = flask_request.headers.get('X-Evonet-Version', '').strip() or connector.get('version') or ''
        _logger.info(
            "Evonet accepted: home=%s device=%s platform=%s addr=%s",
            home_id, device_name, platform, remote_addr,
        )

        with self._lock:
            self._connections[home_id] = ws

        try:
            from models.db import db
            db.update_connector(connector_id, {
                'last_seen_at': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                'device_name': device_name,
                'platform': platform,
                'version': version,
            })
            from backend.homes.manager import home_manager
            home_manager.on_connector_connected(home_id, ws)
        except Exception as e:
            _logger.error("Error registering connector for home %s: %s", home_id, e)
            ws.close()
            return

        self._emit('connector_connected', {
            'home_id': home_id,
            'device_name': device_name,
            'platform': platform,
        })

        msg_count = 0
        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    break
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    _logger.debug("Received non-JSON from Evonet (home=%s): %r", home_id, raw)
                    continue

                if data.get('type') == 'ping':
                    _logger.debug("Ping from home=%s, sending pong", home_id)
                    try:
                        ws.send(json.dumps({'type': 'pong'}))
                    except Exception:
                        break
                    continue

                msg_count += 1
                _logger.debug("Message #%d from home=%s method=%s", msg_count, home_id, data.get('method') or data.get('type'))
                try:
                    from backend.homes.manager import home_manager
                    home_manager.on_connector_message(home_id, data)
                except Exception as e:
                    _logger.error("Error routing message for home %s: %s", home_id, e)

        except Exception as e:
            _logger.info("Evonet connection closed for home=%s: %s", home_id, e)
        finally:
            with self._lock:
                self._connections.pop(home_id, None)

            _logger.info("Evonet disconnected: home=%s device=%s (handled %d messages)", home_id, device_name, msg_count)
            try:
                from backend.homes.manager import home_manager
                home_manager.on_connector_disconnected(home_id)
            except Exception:
                pass
            self._emit('connector_disconnected', {'home_id': home_id})

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _authenticate(self, flask_request):
        auth = flask_request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return None, None
        token = auth[len('Bearer '):]
        try:
            from models.db import db
            connector = db.get_connector_by_token(token)
        except Exception as e:
            _logger.error("DB error during connector auth: %s", e)
            return None, None
        if not connector:
            _logger.debug("Connector auth failed: token not found in DB")
            return None, None
        if not connector.get('home_id'):
            _logger.debug("Connector auth failed: connector has no home_id")
            return None, None
        return connector, connector['home_id']

    def _emit(self, event: str, data: dict) -> None:
        try:
            from backend.event_stream import event_stream
            event_stream.emit(event, data)
        except Exception:
            pass


# Module-level singleton
connector_relay = ConnectorRelay()
