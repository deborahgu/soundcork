"""Allowlist of known speaker IPs loaded from the DataStore.

Used to restrict Bose protocol endpoints to known speakers and to validate
speaker proxy targets in the webui.
"""

import ipaddress
import logging

from soundcork.datastore import DataStore

logger = logging.getLogger(__name__)

# Always allow loopback addresses (local development)
_LOOPBACK = frozenset({"127.0.0.1", "::1"})


_RFC1918_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def _is_private_ip(ip: str) -> bool:
    """Check if an IP is in a private RFC1918 range.

    Uses explicit network checks instead of ``ipaddress.is_private`` which
    is too broad (includes TEST-NET, link-local 169.254, etc.).
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if not isinstance(addr, ipaddress.IPv4Address):
        return False
    return any(addr in net for net in _RFC1918_NETWORKS)


class SpeakerAllowlist:
    """Maintains a cached set of IP addresses for registered speakers."""

    def __init__(self, datastore: DataStore) -> None:
        self._datastore = datastore
        self._allowed_ips: set[str] = set()
        self.refresh()

    def refresh(self) -> None:
        """Reload allowed IPs from the datastore."""
        ips: set[str] = set()
        try:
            for account_id in self._datastore.list_accounts():
                if not account_id:
                    continue
                try:
                    for device_id in self._datastore.list_devices(account_id):
                        if not device_id:
                            continue
                        try:
                            info = self._datastore.get_device_info(account_id, device_id)
                            if info.ip_address:
                                ips.add(info.ip_address)
                        except Exception:
                            logger.warning(
                                "Failed to read device info for %s/%s",
                                account_id,
                                device_id,
                                exc_info=True,
                            )
                except Exception:
                    logger.warning(
                        "Failed to list devices for account %s",
                        account_id,
                        exc_info=True,
                    )
        except Exception:
            logger.warning("Failed to list accounts", exc_info=True)

        self._allowed_ips = ips
        logger.info("Speaker allowlist refreshed: %d IPs", len(ips))

    def is_allowed(self, ip: str) -> bool:
        """Check if an IP belongs to a known speaker, loopback, or private network.

        Private IPs (RFC1918) are allowed because speakers behind NAT appear
        with the router's LAN IP rather than their own.
        """
        return ip in _LOOPBACK or ip in self._allowed_ips or _is_private_ip(ip)

    def is_registered_speaker(self, ip: str) -> bool:
        """Check if an IP is a registered speaker (excludes loopback)."""
        return ip in self._allowed_ips

    def get_allowed_ips(self) -> set[str]:
        """Return a copy of the current allowed IP set."""
        return set(self._allowed_ips)
