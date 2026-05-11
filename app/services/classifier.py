"""
classifier.py — Classifies an IP as corporate, isp, hosting, vpn, or unknown.
Uses IPinfo metadata and keyword matching against known provider lists.
"""

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import ISP_KEYWORDS, HOSTING_KEYWORDS, VPN_KEYWORDS, MOBILE_KEYWORDS, GOV_KEYWORDS, PRIVATE_KEYWORDS


class IPClassifier:
    """
    Determines whether an IP belongs to a corporate network or should be rejected.

    Classification priority:
      1. VPN / Proxy  (reject)
      2. Cloud Hosting (reject)
      3. Mobile / GSM (reject)
      4. Government (reject)
      5. Private Customer (reject)
      6. ISP / Residential (reject)
      7. Corporate (accept)
    """

    def classify(self, ipinfo_data: dict) -> dict:
        """
        Run classification logic on raw IPinfo response.

        Args:
            ipinfo_data: dict returned by IPLookupService.lookup()

        Returns:
            dict with keys: classification (str), reason (str), should_process (bool)
        """
        org = ipinfo_data.get("org", "").lower()
        hostname = ipinfo_data.get("hostname", "").lower()
        privacy = ipinfo_data.get("privacy", {})
        company_type = ipinfo_data.get("company", {}).get("type", "").lower()

        # ── 1. Check IPinfo privacy flags (paid plan) ──────────────────────
        if privacy:
            if privacy.get("vpn") or privacy.get("proxy") or privacy.get("tor"):
                return self._result("vpn", "IPinfo privacy flag: VPN/Proxy/Tor", False)
            if privacy.get("hosting"):
                return self._result("hosting", "IPinfo privacy flag: Hosting", False)

        # ── 2. Check company type from IPinfo (paid plan) ──────────────────
        if company_type in ("isp", "education", "hosting"):
            label = "isp" if company_type == "isp" else company_type
            return self._result(label, f"IPinfo company type: {company_type}", False)

        # ── 3. VPN keyword match ───────────────────────────────────────────
        if self._matches_keywords(org, VPN_KEYWORDS) or \
           self._matches_keywords(hostname, VPN_KEYWORDS):
            return self._result("vpn", f"Keyword match: VPN provider in org='{org}'", False)

        # ── 4. Hosting keyword match ───────────────────────────────────────
        if self._matches_keywords(org, HOSTING_KEYWORDS) or \
           self._matches_keywords(hostname, HOSTING_KEYWORDS):
            return self._result("hosting", f"Keyword match: Cloud/Hosting in org='{org}'", False)

        # ── 5. Mobile/GSM keyword match ────────────────────────────────────
        if self._matches_keywords(org, MOBILE_KEYWORDS) or \
           self._matches_keywords(hostname, MOBILE_KEYWORDS):
            return self._result("mobile", f"Keyword match: Mobile/GSM in org='{org}'", False)

        # ── 6. Government keyword match ────────────────────────────────────
        if self._matches_keywords(org, GOV_KEYWORDS) or \
           self._matches_keywords(hostname, GOV_KEYWORDS):
            return self._result("gov", f"Keyword match: Government body in org='{org}'", False)

        # ── 7. Private Customer keyword match ──────────────────────────────
        if self._matches_keywords(org, PRIVATE_KEYWORDS) or \
           self._matches_keywords(hostname, PRIVATE_KEYWORDS):
            return self._result("isp", f"Keyword match: Private Customer in org='{org}'", False)

        # ── 8. ISP keyword match ───────────────────────────────────────────
        if self._matches_keywords(org, ISP_KEYWORDS) or \
           self._matches_keywords(hostname, ISP_KEYWORDS):
            return self._result("isp", f"Keyword match: ISP provider in org='{org}'", False)

        # ── 6. Heuristic: org has no name ─────────────────────────────────
        # Small or unlisted organizations won't appear in IPinfo at all.
        # We give them a soft-pass (should_process=True) so the pipeline
        # can attempt reverse DNS and web scraping to identify them.
        # Truly residential/dynamic IPs will usually be caught by ISP keywords above.
        if not org or org.strip() == "":
            return self._result(
                "unknown_org",
                "Empty org string — small/unlisted org; will try reverse-DNS + scrape",
                True,   # ← SOFT PASS: continue pipeline instead of rejecting
            )

        # ── 7. Classify as corporate if none of the above matched ──────────
        return self._result("corporate", f"No rejection signals found for org='{org}'", True)

    def _matches_keywords(self, text: str, keywords: list) -> bool:
        """Return True if any keyword is found in the given text string."""
        return any(kw in text for kw in keywords)

    def _result(self, classification: str, reason: str, should_process: bool) -> dict:
        """Build a standardized classification result dict."""
        return {
            "classification": classification,
            "reason": reason,
            "should_process": should_process,
        }
