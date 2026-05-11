"""
apollo_enrichment.py — Queries Apollo.io to enrich a company domain with firmographic data.
Falls back to web scraping (company website → Google search) when Apollo has no data.
"""

import requests

try:
    from app.config import APOLLO_API_KEY
    from app.services.logger import get_logger
    from app.services.web_scraper import WebScraperService
except ImportError:
    try:
        from config import APOLLO_API_KEY
        from services.logger import get_logger
        from services.web_scraper import WebScraperService
    except ImportError:
        APOLLO_API_KEY = ""
        def get_logger(name):
            import logging
            return logging.getLogger(name)
        WebScraperService = None

logger = get_logger("apollo_service")

# Module-level scraper instance (created once)
_scraper = WebScraperService() if WebScraperService else None


class ApolloEnrichmentService:
    """
    Calls the Apollo.io Organization Enrichment API to get company details
    from a domain name.

    Fallback chain:
      1. Apollo.io enrichment API (by domain)
      2. Apollo.io search API     (by company name → domain)
      3. Direct website scrape    (meta/OG tags from homepage)
      4. Google search scrape     (first result snippet)

    Docs: https://apolloio.github.io/apollo-api-docs/?shell#organization-enrichment
    """

    APOLLO_ORG_ENDPOINT = "https://api.apollo.io/v1/organizations/enrich"
    APOLLO_SEARCH_ENDPOINT = "https://api.apollo.io/v1/organizations/search"

    def _search_domain_by_name(self, name: str) -> str:
        """
        Calls Apollo Search API to find the best domain match for a company name.
        """
        try:
            headers = {
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": APOLLO_API_KEY,
            }
            payload = {
                "q_organization_name": name,
                "page": 1,
                "display_mode": "regular"
            }
            response = requests.post(
                self.APOLLO_SEARCH_ENDPOINT,
                headers=headers,
                json=payload,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                orgs = data.get("organizations", [])
                if orgs:
                    # Return the domain of the first (best) match
                    return orgs[0].get("primary_domain") or orgs[0].get("website_url", "").replace("http://", "").replace("https://", "").split("/")[0]
            return ""
        except Exception as e:
            logger.error(f"Apollo Search Error: {str(e)}")
            return ""

    def enrich(self, domain: str, company_name: str = "") -> dict:
        """
        Fetch company firmographics from Apollo.
        If domain is missing, dynamically searches for it using the company name.
        """
        if not APOLLO_API_KEY:
            logger.error("Apollo API Key is missing in enrichment service!")
            return self._mock_response(domain, reason="No Apollo API key configured", company_name=company_name)
        
        logger.debug(f"Apollo Key check: {APOLLO_API_KEY[:4]}...{APOLLO_API_KEY[-4:]}")

        # ── Step A: Dynamic Domain Resolution (If domain is missing) ──────────
        if not domain and company_name:
            logger.info(f"Searching Apollo for domain matching name: '{company_name}'")
            resolved_domain = self._search_domain_by_name(company_name)
            if resolved_domain:
                domain = resolved_domain
                logger.info(f"Dynamically resolved '{company_name}' to '{domain}'")
            else:
                logger.warning(f"Could not dynamically resolve '{company_name}' to a domain")
                return self._mock_response("", reason="Could not dynamically resolve name to a domain", company_name=company_name)

        if not domain:
            return self._mock_response("", reason="No domain or company name available")

        try:
            headers = {
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": APOLLO_API_KEY,
            }
            params = {
                "domain": domain,
            }

            response = requests.get(
                self.APOLLO_ORG_ENDPOINT,
                headers=headers,
                params=params,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                org = data.get("organization", {})

                if not org:
                    logger.warning(f"Apollo returned 200 but empty organization for {domain}")
                    return self._scrape_fallback(
                        domain, company_name,
                        reason="Apollo returned empty organization"
                    )

                return self._parse_apollo_org(org)

            elif response.status_code == 401:
                logger.error(f"Apollo 401 Unauthorized for {domain}. Check API Key.")
                return self._scrape_fallback(
                    domain, company_name,
                    reason="Apollo API key invalid or unauthorized"
                )

            elif response.status_code == 404:
                logger.info(f"Apollo 404 Not Found for {domain}")
                return self._scrape_fallback(
                    domain, company_name,
                    reason="Domain not found in Apollo database"
                )

            else:
                logger.error(f"Apollo error {response.status_code} for {domain}: {response.text}")
                return self._scrape_fallback(
                    domain, company_name,
                    reason=f"Apollo returned HTTP {response.status_code}"
                )

        except requests.exceptions.Timeout:
            return self._scrape_fallback(domain, company_name, reason="Apollo API request timed out")
        except Exception as e:
            return self._scrape_fallback(domain, company_name, reason=f"Apollo error: {str(e)}")

    def _parse_apollo_org(self, org: dict) -> dict:
        """
        Extract relevant fields from Apollo organization object.
        Returns a clean, flat dict of company information.
        """
        return {
            "name": org.get("name", ""),
            "domain": org.get("primary_domain", ""),
            "industry": org.get("industry", ""),
            "sub_industry": org.get("keywords", []),
            "employee_count": org.get("estimated_num_employees", None),
            "employee_range": org.get("employee_count", ""),
            "revenue_range": org.get("annual_revenue_printed", ""),
            "founded_year": org.get("founded_year", None),
            "description": org.get("short_description", ""),
            "linkedin_url": org.get("linkedin_url", ""),
            "website_url": org.get("website_url", ""),
            "phone": org.get("sanitized_phone", ""),
            "city": org.get("city", ""),
            "state": org.get("state", ""),
            "country": org.get("country", ""),
            "source": "apollo",
            "mock": False,
        }

    def patch_partial_with_scrape(
        self, company_data: dict, domain: str, org_name: str = ""
    ) -> dict:
        """
        PUBLIC — Called by identify.py whenever company_data is partial (mock=True
        or key fields are missing). Runs a deep scrape and fills every empty
        field in-place.

        Returns an updated company_data dict. Fields already populated by
        Apollo are preserved; empty ones are filled from scraping.
        """
        logger.info(
            f"[patch_partial] Patching partial data for domain='{domain}' "
            f"org='{org_name}'"
        )

        if not _scraper:
            return company_data

        scraped = _scraper.deep_scrape_company(domain=domain, org_name=org_name)
        if not scraped:
            logger.warning(f"[patch_partial] Deep scrape returned nothing for '{domain}'")
            return company_data

        # ── Merge: fill only empty / unknown fields ────────────────────────
        # Fields we want to complete
        patchable_fields = [
            "name", "description", "industry", "employee_range",
            "founded_year", "linkedin_url", "website_url",
            "phone", "city", "state", "country",
        ]
        patched_count = 0
        for field in patchable_fields:
            existing = company_data.get(field)
            scraped_val = scraped.get(field)
            # Overwrite if existing is empty / None / "Unknown"
            if not existing or existing in ("Unknown", "Unknown (mock)"):
                if scraped_val and scraped_val not in ("Unknown", ""):
                    company_data[field] = scraped_val
                    patched_count += 1

        # Always update metadata fields
        company_data["mock"] = False
        company_data["scrape_fallback"] = True
        if company_data.get("source") in ("mock", "", None):
            company_data["source"] = scraped.get("source", "deep_scrape")

        logger.info(
            f"[patch_partial] Patched {patched_count} fields for '{domain}'. "
            f"name='{company_data.get('name')}' | "
            f"industry='{company_data.get('industry')}' | "
            f"city='{company_data.get('city')}'"
        )
        return company_data

    def _scrape_fallback(
        self, domain: str, company_name: str = "", reason: str = ""
    ) -> dict:
        """
        When Apollo has no data, run a full deep scrape to fill all fields.
        """
        logger.info(
            f"Apollo failed ({reason}). Starting deep-scrape fallback for "
            f"domain='{domain}' name='{company_name}'"
        )

        if _scraper:
            scraped = _scraper.deep_scrape_company(
                domain=domain, org_name=company_name
            )
            if scraped:
                scraped["apollo_miss_reason"] = reason
                return scraped

        # All fallbacks failed — return a minimal mock
        logger.warning(
            f"All enrichment strategies failed for domain='{domain}' "
            f"name='{company_name}'. Returning mock."
        )
        return self._mock_response(domain, reason=reason, company_name=company_name)

    def _mock_response(self, domain: str, reason: str = "", company_name: str = "") -> dict:
        """
        Last-resort fallback when Apollo AND all scraping strategies fail.
        """
        name = company_name or (f"Company at {domain}" if domain else "Unknown Company")
        return {
            "name": name,
            "domain": domain or "",
            "industry": "Unknown",
            "sub_industry": [],
            "employee_count": None,
            "employee_range": "Unknown",
            "revenue_range": "Unknown",
            "founded_year": None,
            "description": f"No data found via Apollo or web scraping. Reason: {reason}",
            "linkedin_url": "",
            "website_url": f"https://{domain}" if domain else "",
            "phone": "",
            "city": "",
            "state": "",
            "country": "",
            "source": "mock",
            "mock": True,
            "mock_reason": reason,
        }
