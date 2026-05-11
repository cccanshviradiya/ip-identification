"""
reverse_dns.py — Performs reverse DNS (PTR record) lookup for an IP address.
Uses Python's socket library — no external API required.
"""

import socket
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))


class ReverseDNSService:
    """
    Resolves the PTR record (reverse DNS) for a given IP address.
    Example: 103.21.244.1 → mail.infosys.com
    """

    def lookup(self, ip: str) -> dict:
        """
        Perform reverse DNS lookup.

        Args:
            ip: IPv4 address string.

        Returns:
            dict with keys: hostname (str), success (bool), error (optional str)
        """
        try:
            # socket.gethostbyaddr returns (hostname, aliaslist, ipaddrlist)
            hostname, aliases, _ = socket.gethostbyaddr(ip)

            return {
                "hostname": hostname,
                "aliases": aliases,
                "success": True,
            }

        except socket.herror as e:
            # herror is raised when the host is not found
            return {
                "hostname": "",
                "aliases": [],
                "success": False,
                "error": f"No PTR record found: {e}",
            }
        except socket.timeout:
            return {
                "hostname": "",
                "aliases": [],
                "success": False,
                "error": "Reverse DNS lookup timed out",
            }
        except Exception as e:
            return {
                "hostname": "",
                "aliases": [],
                "success": False,
                "error": f"Reverse DNS error: {str(e)}",
            }
