"""
domain_extractor.py — Extracts the root domain from a hostname or org string.
Handles subdomain stripping and known generic/hosting domain filtering.
"""

import re
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import GENERIC_DOMAINS_BLACKLIST, CORPORATE_DOMAIN_MAP


class DomainExtractorService:
    """
    Extracts a clean root domain (e.g. infosys.com) from:
      - Reverse DNS hostnames (e.g. mail.infosys.com)
      - IPinfo org strings (e.g. "AS12345 Infosys Limited")
      - WHOIS org/netname fields
    """

    # Common second-level domains in India and globally
    KNOWN_SLD_TLDS = [
        ".co.in", ".net.in", ".org.in", ".gov.in", ".edu.in",
        ".co.uk", ".org.uk", ".me.uk", ".net.uk",
        ".com.au", ".net.au",
    ]

    def extract_from_hostname(self, hostname: str) -> str:
        """
        Strip subdomains and return the root domain.
        """
        if not hostname:
            return ""

        hostname = hostname.strip().lower()

        # Reject known infrastructure/generic domains
        for blocked in GENERIC_DOMAINS_BLACKLIST:
            if hostname.endswith(blocked) or hostname == blocked:
                return ""

        # Reject ASN-style technical domains (e.g. as45671.net, as123.com)
        if re.match(r"^as\d+\.(com|net|org|in|co\.in)$", hostname):
            return ""

        # Handle known compound SLD+TLD patterns (e.g. .co.in)
        for sld_tld in self.KNOWN_SLD_TLDS:
            if hostname.endswith(sld_tld):
                # Strip the SLD+TLD, take the last remaining part
                base = hostname[: -len(sld_tld)]
                parts = base.split(".")
                if not parts[-1]: return "" # edge case
                return parts[-1] + sld_tld

        # Standard TLD: take last 2 parts
        parts = hostname.split(".")
        if len(parts) >= 2:
            # Check if the root part is just an ASN (e.g. as45671.net)
            root_part = parts[-2]
            if re.match(r"^as\d+$", root_part):
                return ""
            return ".".join(parts[-2:])

        return ""

    def extract_from_org(self, org_string: str) -> str:
        """
        Try to find a domain-like pattern inside an org string.
        e.g. "AS12345 Infosys BPM Limited" → no domain, returns ""
        """
        if not org_string:
            return ""

        # Look for anything resembling a FQDN in the string
        pattern = r"([a-zA-Z0-9\-]+\.[a-zA-Z]{2,})"
        matches = re.findall(pattern, org_string)
        for match in matches:
            match = match.lower()
            # Skip if it's in the blacklist
            if not any(bl in match for bl in GENERIC_DOMAINS_BLACKLIST):
                return match

        return ""

    def map_name_to_domain(self, name: str) -> str:
        """
        Check if the clean name matches a known corporate domain map.
        """
        if not name:
            return ""
        
        name_lower = name.lower()
        for key, domain in CORPORATE_DOMAIN_MAP.items():
            if key in name_lower:
                return domain
        return ""

    def clean_org_name(self, org_string: str) -> str:
        """
        Clean up an org string into a searchable company name.
        Example: "AS15169 Google LLC" → "Google LLC"
        """
        if not org_string:
            return ""
        
        # Remove AS number (e.g. AS12345)
        clean = re.sub(r"^as\d+\s+", "", org_string, flags=re.IGNORECASE)
        # Remove common ISP/Hosting prefixes if they are just prefixes
        clean = clean.strip()
        
        return clean

    def extract_from_whois(self, whois_data: dict) -> str:
        """
        Extract a domain from WHOIS data fields (domain_name, emails, etc.).
        """
        if not whois_data:
            return ""

        # Prefer the domain_name field directly from WHOIS
        domain_name = whois_data.get("domain_name", "")
        if isinstance(domain_name, list):
            domain_name = domain_name[0] if domain_name else ""

        if domain_name:
            return domain_name.strip().lower()

        # Fall back to email domain if available
        emails = whois_data.get("emails", [])
        if isinstance(emails, str):
            emails = [emails]
        for email in emails:
            if "@" in email:
                return email.split("@")[-1].lower()

        return ""
