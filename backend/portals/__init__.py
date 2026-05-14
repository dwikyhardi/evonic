"""
Portals — virtual path mapping for agent file I/O.

Portals allow mapping a local or remote directory to a virtual path visible
to agents under the /_portal/ prefix. They are intercepted at the file I/O
tool level (read_file, write_file, patch, str_replace) and routed to the
appropriate backend: local, SSH, or evonet (cloud workplace).
"""

from backend.portals.manager import PortalManager

portal_manager = PortalManager()
