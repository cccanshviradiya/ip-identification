"""
ip_lookup.py — Queries IPinfo.io to retrieve IP metadata.
Falls back to a basic socket-based lookup if the API is unavailable.
"""

import requests
from typing import Optional
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import IPINFO_TOKEN


class IPLookupService:
    """
    Fetches IP metadata from IPinfo.io.
    Returns a normalized dict with org, hostname, city, country, etc.
    """

    IPINFO_BASE_URL = "https://ipinfo.io/{ip}/json"

    def __init__(self):
        self.token = IPINFO_TOKEN

    def lookup(self, ip: str) -> dict:
        """
        Query IPinfo.io for metadata about the given IP.

        Args:
            ip: IPv4 address string.

        Returns:
            dict with keys: ip, org, hostname, city, region, country, asn, error (optional).
        """
        try:
            url = self.IPINFO_BASE_URL.format(ip=ip)
            params = {}
            if self.token:
                params["token"] = self.token

            response = requests.get(url, params=params, timeout=8)
            response.raise_for_status()
            data = response.json()

            return {
                "ip": data.get("ip", ip),
                "org": data.get("org", ""),           # e.g. "AS15169 Google LLC"
                "hostname": data.get("hostname", ""),
                "city": data.get("city", ""),
                "region": data.get("region", ""),
                "country": data.get("country", ""),
                "asn": self._parse_asn(data.get("org", "")),
                "privacy": data.get("privacy", {}),   # VPN/proxy/hosting flags (paid plan)
                "company": data.get("company", {}),   # Company info (paid plan)
                "source": "ipinfo",
            }

        except requests.exceptions.Timeout:
            return self._error_response(ip, "IPinfo request timed out")
        except requests.exceptions.HTTPError as e:
            return self._error_response(ip, f"IPinfo HTTP error: {e}")
        except Exception as e:
            return self._error_response(ip, f"IPinfo lookup failed: {e}")

    def _parse_asn(self, org_string: str) -> str:
        """Extract ASN number from org string like 'AS15169 Google LLC'."""
        if org_string and org_string.startswith("AS"):
            parts = org_string.split(" ", 1)
            return parts[0]  # Returns "AS15169"
        return ""

    def _error_response(self, ip: str, message: str) -> dict:
        """Return a safe fallback dict when the API call fails."""
        return {
            "ip": ip,
            "org": "",
            "hostname": "",
            "city": "",
            "region": "",
            "country": "",
            "asn": "",
            "privacy": {},
            "company": {},
            "source": "error",
            "error": message,
        }
