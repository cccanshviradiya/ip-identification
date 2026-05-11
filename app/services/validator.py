"""
validator.py — Validates a domain using MX record checks and WHOIS age.
Ensures we're only enriching real, active business domains.
"""

import dns.resolver
import whois
from datetime import datetime, timezone
from typing import Optional
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))


class DomainValidatorService:
    """
    Validates a domain through two checks:
      1. MX Records — the domain must have at least one mail server.
      2. Domain Age  — domain must be older than 6 months (via WHOIS).
    """

    MINIMUM_DOMAIN_AGE_DAYS = 180  # ~6 months

    def validate(self, domain: str) -> dict:
        """
        Run all validation checks on the given domain.

        Args:
            domain: Root domain string (e.g. "infosys.com")

        Returns:
            dict with keys: valid (bool), reason (str), checks (dict)
        """
        if not domain:
            return self._fail("Empty domain string provided", {})

        checks = {}

        # ── Check 1: MX Records ───────────────────────────────────────────
        mx_result = self._check_mx_records(domain)
        checks["mx_records"] = mx_result

        if not mx_result["passed"]:
            return self._fail(f"No MX records: {mx_result['detail']}", checks)

        # ── Check 2: Domain Age ───────────────────────────────────────────
        age_result = self._check_domain_age(domain)
        checks["domain_age"] = age_result

        if not age_result["passed"]:
            return self._fail(f"Domain too new or age unknown: {age_result['detail']}", checks)

        # ── All checks passed ─────────────────────────────────────────────
        return {
            "valid": True,
            "reason": "All validation checks passed",
            "checks": checks,
        }

    def _check_mx_records(self, domain: str) -> dict:
        """
        Query DNS for MX records on the domain.
        Returns passed=True if at least one MX record exists.
        """
        try:
            answers = dns.resolver.resolve(domain, "MX", lifetime=8)
            mx_list = [str(r.exchange).rstrip(".") for r in answers]
            return {
                "passed": len(mx_list) > 0,
                "detail": f"Found {len(mx_list)} MX record(s): {mx_list[:3]}",
            }
        except dns.resolver.NXDOMAIN:
            return {"passed": False, "detail": "Domain does not exist (NXDOMAIN)"}
        except dns.resolver.NoAnswer:
            return {"passed": False, "detail": "No MX records found (NoAnswer)"}
        except dns.resolver.Timeout:
            return {"passed": False, "detail": "DNS query timed out"}
        except Exception as e:
            return {"passed": False, "detail": f"MX lookup error: {e}"}

    def _check_domain_age(self, domain: str) -> dict:
        """
        Use WHOIS to find registration date and verify the domain is > 6 months old.
        """
        try:
            w = whois.whois(domain)
            creation_date = w.creation_date

            # creation_date can be a list or a single datetime
            if isinstance(creation_date, list):
                creation_date = creation_date[0]

            if creation_date is None:
                # WHOIS returned no date — treat as okay for established TLDs
                return {
                    "passed": True,
                    "detail": "Creation date not available in WHOIS — assuming valid",
                }

            # Normalize timezone
            if creation_date.tzinfo is None:
                creation_date = creation_date.replace(tzinfo=timezone.utc)

            age_days = (datetime.now(timezone.utc) - creation_date).days

            if age_days >= self.MINIMUM_DOMAIN_AGE_DAYS:
                return {
                    "passed": True,
                    "detail": f"Domain is {age_days} days old (registered: {creation_date.date()})",
                }
            else:
                return {
                    "passed": False,
                    "detail": f"Domain is only {age_days} days old (minimum: {self.MINIMUM_DOMAIN_AGE_DAYS})",
                }

        except Exception as e:
            # WHOIS failures are common — treat as non-blocking for MVP
            return {
                "passed": True,
                "detail": f"WHOIS check skipped (error: {e}) — assuming valid",
            }

    def _fail(self, reason: str, checks: dict) -> dict:
        """Return a standardized failure result."""
        return {
            "valid": False,
            "reason": reason,
            "checks": checks,
        }
