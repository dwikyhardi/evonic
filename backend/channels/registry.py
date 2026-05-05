"""Channel Manager — lifecycle management for active channels."""

import logging
from typing import Dict, Type
from backend.channels.base import BaseChannel
from backend.channels.telegram import TelegramChannel
from backend.channels.whatsapp import WhatsAppChannel
from models.db import db

_logger = logging.getLogger(__name__)

# Map of channel type -> class
CHANNEL_TYPES: Dict[str, Type[BaseChannel]] = {
    'telegram': TelegramChannel,
    'whatsapp': WhatsAppChannel,
}


class ChannelManager:
    def __init__(self):
        self._active: Dict[str, BaseChannel] = {}  # channel_id -> instance

    def start_channel(self, channel_id: str) -> bool:
        """Start a channel by its DB ID. Skips disabled channels."""
        if channel_id in self._active and self._active[channel_id].is_running:
            return True  # already running

        channel_data = db.get_channel(channel_id)
        if not channel_data:
            return False

        if not channel_data.get('enabled'):
            _logger.debug("Skipping disabled channel %s", channel_id)
            return False

        # Don't start channels for disabled agents
        agent = db.get_agent(channel_data['agent_id'])
        if agent and not agent.get('enabled', True):
            _logger.debug("Skipping channel %s — agent %s is disabled", channel_id, channel_data['agent_id'])
            return False

        chan_type = channel_data.get('type')
        cls = CHANNEL_TYPES.get(chan_type)
        if not cls:
            raise ValueError(f"Unknown channel type: {chan_type}")

        config = channel_data.get('config', {})
        if isinstance(config, str):
            import json
            config = json.loads(config)

        instance = cls(channel_id, channel_data['agent_id'], config)
        instance.start()
        self._active[channel_id] = instance
        return True

    def stop_channel(self, channel_id: str) -> bool:
        """Stop a running channel."""
        instance = self._active.get(channel_id)
        if not instance:
            return False
        instance.stop()
        del self._active[channel_id]
        return True

    def get_channel_instance(self, channel_id: str) -> BaseChannel | None:
        """Return the active channel instance for the given channel_id, or None."""
        return self._active.get(channel_id)

    def is_running(self, channel_id: str) -> bool:
        instance = self._active.get(channel_id)
        return instance.is_running if instance else False

    def start_all_enabled(self):
        """Start all enabled channels from DB (called at app startup).
        Skips channels belonging to disabled agents."""
        agents = db.get_agents()
        for agent in agents:
            if not agent.get('enabled', True):
                continue  # skip disabled agents entirely
            channels = db.get_channels(agent['id'])
            for ch in channels:
                if ch.get('enabled'):
                    try:
                        self.start_channel(ch['id'])
                    except Exception as e:
                        _logger.error("Failed to start channel %s: %s", ch['id'], e)

    def stop_all(self):
        """Stop all running channels."""
        for channel_id in list(self._active.keys()):
            self.stop_channel(channel_id)


# Global instance
channel_manager = ChannelManager()
