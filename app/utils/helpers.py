"""
helpers.py — Shared utility functions used across the application.
"""

import re
import ipaddress
from typing import Optional


def is_private_ip(ip: str) -> bool:
    """
    Returns True if the IP is a private/reserved/loopback address
    that cannot be looked up via external APIs.
    """
    try:
        if "/" in ip:
            net = ipaddress.IPv4Network(ip, strict=False)
            addr = net.network_address
        else:
            addr = ipaddress.IPv4Address(ip)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
        )
    except ValueError:
        return False


def is_valid_ipv4(ip: str) -> bool:
    """
    Check if a string is a valid IPv4 address or CIDR block.
    Accepts both public AND private IPs — callers handle the distinction.
    """
    try:
        if "/" in ip:
            net = ipaddress.IPv4Network(ip, strict=False)
            return net.version == 4
        else:
            ipaddress.IPv4Address(ip)
            return True
    except ValueError:
        return False


def sanitize_domain(domain: str) -> str:
    """
    Clean and normalize a domain string.
    Removes http(s)://, trailing slashes, whitespace, and converts to lowercase.

    Args:
        domain: Raw domain or URL string.

    Returns:
        Cleaned lowercase domain string.
    """
    if not domain:
        return ""

    domain = domain.strip().lower()
    # Remove protocol prefix
    domain = re.sub(r"^https?://", "", domain)
    # Remove www prefix
    domain = re.sub(r"^www\.", "", domain)
    # Remove trailing slash and path
    domain = domain.split("/")[0]
    # Remove port number
    domain = domain.split(":")[0]

    return domain


def truncate(text: str, max_len: int = 200) -> str:
    """Safely truncate a string for DB storage."""
    if not text:
        return ""
    return text[:max_len]


def build_rejection_response(ip: str, classification: str, reason: str) -> dict:
    """
    Build a standardized rejection response when the IP is not corporate.

    Args:
        ip: The input IP address.
        classification: e.g. 'isp', 'hosting', 'vpn'.
        reason: Human-readable explanation.

    Returns:
        Structured dict suitable for returning as an API response.
    """
    return {
        "ip": ip,
        "status": "rejected",
        "classification": classification,
        "reason": reason,
        "hostname": None,
        "domain": None,
        "validated": False,
        "company": None,
    }
