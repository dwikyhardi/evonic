"""
evonic.http — stdlib HTTP client (urllib-based, no extra dependencies).

Works when the container has network access (SANDBOX_NETWORK=bridge).
"""

import json as _json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


class Response:
    """HTTP response wrapper."""

    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.headers = headers
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode('utf-8', errors='replace')

    @property
    def data(self) -> bytes:
        return self._body

    def json(self):
        """Parse response body as JSON."""
        return _json.loads(self._body)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def __repr__(self):
        return f'<Response status={self.status} length={len(self._body)}>'


def _make_request(url: str, method: str = 'GET', data: bytes = None,
                  headers: dict = None, timeout: int = 10) -> Response:
    req_headers = {'User-Agent': 'evonic-http/1.0'}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return Response(
                status=resp.status,
                headers=dict(resp.headers),
                body=resp.read(),
            )
    except urllib.error.HTTPError as e:
        return Response(
            status=e.code,
            headers=dict(e.headers),
            body=e.read(),
        )
    except urllib.error.URLError as e:
        raise ConnectionError(str(e.reason)) from e


def get(url: str, headers: dict = None, timeout: int = 10) -> Response:
    """Perform an HTTP GET request.

    Args:
        url:     Target URL.
        headers: Optional request headers dict.
        timeout: Request timeout in seconds (default: 10).

    Returns:
        Response object with .status, .text, .json(), .ok, .headers.

    Example:
        r = get('https://api.example.com/data')
        print(r.json())
    """
    return _make_request(url, method='GET', headers=headers, timeout=timeout)


def post(url: str, data=None, json=None, headers: dict = None,
         timeout: int = 10) -> Response:
    """Perform an HTTP POST request.

    Args:
        url:     Target URL.
        data:    Raw bytes or string body.
        json:    Python object to JSON-encode (sets Content-Type automatically).
        headers: Optional request headers dict.
        timeout: Request timeout in seconds (default: 10).

    Returns:
        Response object.

    Example:
        r = post('https://api.example.com/submit', json={'key': 'value'})
        print(r.status, r.json())
    """
    req_headers = dict(headers or {})

    if json is not None:
        body = _json.dumps(json).encode('utf-8')
        req_headers.setdefault('Content-Type', 'application/json')
    elif data is not None:
        body = data.encode('utf-8') if isinstance(data, str) else data
        req_headers.setdefault('Content-Type', 'application/x-www-form-urlencoded')
    else:
        body = b''

    return _make_request(url, method='POST', data=body, headers=req_headers, timeout=timeout)


def download(url: str, path: str, timeout: int = 30) -> dict:
    """Download a URL to a local file.

    Args:
        url:     Source URL.
        path:    Destination file path.
        timeout: Download timeout in seconds (default: 30).

    Returns:
        dict with keys: path, bytes_written, status.

    Example:
        download('https://example.com/file.zip', '/workspace/file.zip')
    """
    resp = _make_request(url, timeout=timeout)
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, 'wb') as f:
        f.write(resp.data)
    return {
        'path': abs_path,
        'bytes_written': len(resp.data),
        'status': resp.status,
    }
