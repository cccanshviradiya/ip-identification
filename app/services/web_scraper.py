"""
web_scraper.py — Scrapes company information as a fallback when Apollo API
has no data for a domain or when IPinfo doesn't know the organization.

Strategies (in order of richness):
  1. deep_scrape_company()  — Multi-page crawl: homepage + About + Contact
                               pages, plus Google Knowledge Panel.
                               Fills: name, description, industry, phone,
                               city, state, country, employee_range,
                               founded_year, linkedin_url, website_url.

  2. scrape_company_website() — Single-page scrape of homepage only.
                                 Quick, lightweight.

  3. scrape_google_for_org()  — Google search snippet for a company name.
                                 Used when no domain is available.

Works with plain requests + html.parser (no Selenium / Playwright needed).
"""

import re
import time
import random
import requests
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

try:
    from app.services.logger import get_logger
except ImportError:
    try:
        from services.logger import get_logger
    except ImportError:
        import logging
        def get_logger(name):
            return logging.getLogger(name)

logger = get_logger("web_scraper")

# ─── Shared headers to mimic a real browser ──────────────────────────────────
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ─── HTML parser: collects <title>, <meta>, <a> tags ─────────────────────────

class _FullPageParser(HTMLParser):
    """Collects title, meta tags, anchor hrefs, and all visible text."""

    def __init__(self):
        super().__init__()
        self.title: str = ""
        self.metas: dict = {}           # name/property → content
        self.links: list = []           # all href values
        self.visible_text: list = []    # all visible text chunks
        self._in_title: bool = False
        self._skip_tags = {"script", "style", "noscript", "head"}
        self._current_skip: str = ""

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = attr_map.get("name") or attr_map.get("property") or ""
            val = attr_map.get("content", "")
            if key and val:
                self.metas[key.lower()] = val
        elif tag == "a":
            href = attr_map.get("href", "")
            if href:
                self.links.append(href)
        elif tag in self._skip_tags:
            self._current_skip = tag

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._current_skip:
            stripped = data.strip()
            if stripped:
                self.visible_text.append(stripped)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == self._current_skip:
            self._current_skip = ""

    def get_body_text(self) -> str:
        return " ".join(self.visible_text)


# ─── Industry keyword map ─────────────────────────────────────────────────────
_INDUSTRY_MAP = {
    "Software / IT": [
        "software", "saas", "cloud", "technology", "tech", "it services",
        "digital", "platform", "devops", "cybersecurity", "ai", "machine learning",
        "data analytics", "erp", "crm", "enterprise software",
    ],
    "Manufacturing": [
        "manufacturing", "industrial", "factory", "plant", "production",
        "machinery", "engineering products", "fabrication", "assembly",
    ],
    "Finance / Banking": [
        "bank", "financial", "insurance", "investment", "fintech",
        "lending", "wealth", "asset management", "brokerage", "capital",
    ],
    "Healthcare / Pharma": [
        "healthcare", "hospital", "pharma", "pharmaceutical", "medical",
        "biotech", "life sciences", "diagnostics", "clinical",
    ],
    "Telecommunications": [
        "telecom", "telecommunications", "network", "broadband",
        "wireless", "mobile operator", "isp", "internet service",
    ],
    "Education": [
        "university", "college", "education", "e-learning", "edtech",
        "school", "academy", "training", "institute",
    ],
    "Retail / E-commerce": [
        "retail", "e-commerce", "ecommerce", "shopping", "marketplace",
        "consumer goods", "store", "commerce",
    ],
    "Energy / Utilities": [
        "energy", "power", "electricity", "utility", "oil", "gas",
        "renewable", "solar", "wind", "petroleum",
    ],
    "Logistics / Transport": [
        "logistics", "transport", "shipping", "freight", "supply chain",
        "warehouse", "courier", "fleet",
    ],
    "Real Estate": [
        "real estate", "property", "realty", "construction", "infrastructure",
        "housing", "commercial space",
    ],
    "Media / Publishing": [
        "media", "publishing", "news", "broadcast", "content", "magazine",
        "advertising", "marketing agency",
    ],
}

# ─── Employee count range patterns found in website text ─────────────────────
_EMPLOYEE_PATTERNS = [
    # "1,000 employees", "5000+ employees"
    r"([\d,]+\+?)\s*employees",
    # "team of 250 people"
    r"team of\s+([\d,]+)",
    # "over 10,000 professionals"
    r"over\s+([\d,]+)\s+(?:professionals|staff|people|members)",
    # "500-1000 employees" range
    r"([\d,]+-[\d,]+)\s*employees",
]

# ─── Founded year patterns ────────────────────────────────────────────────────
_FOUNDED_PATTERNS = [
    r"(?:founded|established|incorporated|since)\s+(?:in\s+)?(\d{4})",
    r"©\s*(\d{4})\b",  # copyright year as last resort
]

# ─── LinkedIn URL pattern ─────────────────────────────────────────────────────
_LINKEDIN_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/company/[a-zA-Z0-9\-_%]+"
)

# ─── Phone number pattern — matches real phone numbers, not IP addresses ──────
# Requirements: starts with optional +, has 7-15 digits, NOT an IP-style string
_PHONE_RE = re.compile(
    r"(?<!\d)"                           # not preceded by a digit
    r"(\+?[1-9][\d\s\-().]{6,18}\d)"   # the phone number
    r"(?!\.\d)"                          # not followed by .digit (IP octet)
)

# ─── City/Country from structured address text ────────────────────────────────
# Crude but works well enough for Contact pages
_ADDRESS_CITY_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"        # Title-cased word(s) = city guess
    r",\s*([A-Z]{2}|[A-Z][a-z]+)\b"             # followed by state code or name
)


# ─── Main Service Class ───────────────────────────────────────────────────────

class WebScraperService:
    """
    Provides:
      • deep_scrape_company(domain, org_name)  — Multi-page scrape that fills
        every company field as completely as possible.

      • scrape_company_website(domain)         — Single-page quick scrape.

      • scrape_google_for_org(org_name)        — Google search snippet.
    """

    GOOGLE_SEARCH_URL = "https://www.google.com/search"
    REQUEST_TIMEOUT = 10  # seconds

    # Candidate sub-paths to look for About / Contact / Company info
    _ABOUT_PATHS = [
        "/about", "/about-us", "/about_us", "/company", "/who-we-are",
        "/our-story", "/overview", "/corporate", "/info",
    ]
    _CONTACT_PATHS = [
        "/contact", "/contact-us", "/contact_us", "/reach-us",
        "/get-in-touch", "/locations", "/offices",
    ]

    # ── PUBLIC: Deep multi-page company scrape ────────────────────────────────

    def deep_scrape_company(self, domain: str, org_name: str = "") -> dict:
        """
        Attempts to fill ALL company fields by:
          1. Scraping the homepage
          2. Scraping the About page (best source for description, founding year,
             employee count, and location)
          3. Scraping the Contact page (best source for phone, city, country)
          4. Scraping the Google Knowledge Panel for structured data

        Returns a rich dict with all fields populated where possible.
        Empty string / None for truly unavailable fields.
        source = "deep_scrape"
        """
        if not domain and not org_name:
            return {}

        logger.info(f"[deep_scrape] Starting deep scrape for domain='{domain}' name='{org_name}'")

        # ── Collect raw data from all sources ─────────────────────────────────
        home_data = {}
        about_data = {}
        contact_data = {}
        google_data = {}

        if domain:
            home_data = self._scrape_page(f"https://{domain}")
            about_data = self._scrape_subpage(domain, self._ABOUT_PATHS)
            contact_data = self._scrape_subpage(domain, self._CONTACT_PATHS)

        if org_name:
            google_data = self._scrape_knowledge_panel(org_name, domain)

        # ── Merge: prefer About page > homepage > Google for textual fields ───
        all_texts = " ".join(filter(None, [
            about_data.get("body_text", ""),
            home_data.get("body_text", ""),
            contact_data.get("body_text", ""),
        ]))

        # Name
        name = (
            home_data.get("og_site_name")
            or home_data.get("app_name")
            or google_data.get("name")
            or org_name
            or (home_data.get("title", "").split("|")[0].split("–")[0].split("-")[0].strip())
            or domain or ""
        )

        # Description: prefer About page meta > homepage meta > Google snippet
        description = (
            about_data.get("description")
            or home_data.get("description")
            or google_data.get("description")
            or ""
        )
        if len(description) > 500:
            description = description[:500].rsplit(" ", 1)[0] + "…"

        # Industry
        industry = self._guess_industry_from_text(
            description + " " + all_texts[:3000]
        )

        # Phone: Contact page first, then homepage
        phone = (
            self._extract_phone(contact_data.get("body_text", ""))
            or self._extract_phone(home_data.get("body_text", ""))
            or google_data.get("phone", "")
        )

        # Location: Contact page first
        city, state, country = self._extract_location(
            contact_data.get("body_text", "")
            + " " + home_data.get("body_text", "")
        )
        # Fall back to meta country tags
        if not country:
            country = (
                home_data.get("geo_country")
                or home_data.get("og_country")
                or google_data.get("country", "")
            )

        # Employee range: search all pages
        employee_range = (
            self._extract_employee_range(all_texts)
            or google_data.get("employee_range", "")
        )

        # Founded year: About page, then homepage, then Google
        founded_year = (
            self._extract_founded_year(about_data.get("body_text", ""))
            or self._extract_founded_year(home_data.get("body_text", ""))
            or google_data.get("founded_year")
        )

        # LinkedIn: scan all page links
        linkedin_url = (
            self._extract_linkedin(home_data.get("links", []))
            or self._extract_linkedin(about_data.get("links", []))
            or google_data.get("linkedin_url", "")
        )

        # Website URL
        website_url = f"https://{domain}" if domain else ""

        result = {
            "name":           name[:120].strip() if name else "",
            "domain":         domain or "",
            "description":    description.strip(),
            "industry":       industry,
            "sub_industry":   [],
            "employee_count": None,
            "employee_range": employee_range,
            "revenue_range":  "Unknown",
            "founded_year":   founded_year,
            "linkedin_url":   linkedin_url,
            "website_url":    website_url,
            "phone":          phone,
            "city":           city,
            "state":          state,
            "country":        country,
            "source":         "deep_scrape",
            "mock":           False,
            "scrape_fallback": True,
        }

        # Log coverage score for debugging
        filled = sum(1 for v in result.values() if v and v not in ("Unknown", "deep_scrape", False, True, []))
        logger.info(
            f"[deep_scrape] Complete for '{domain}': "
            f"{filled}/{len(result)} fields filled. "
            f"name='{result['name']}' | industry='{industry}' | "
            f"city='{city}' | founded={founded_year}"
        )
        return result

    # ── PUBLIC: Single-page website scrape ───────────────────────────────────

    def scrape_company_website(self, domain: str) -> dict:
        """
        Fetch https://<domain> and parse OG/meta tags plus visible text.
        Returns a dict with: name, description, website_url, source="web_scrape"
        Returns {} on failure.
        """
        if not domain:
            return {}

        page = self._scrape_page(f"https://{domain}")
        if not page:
            return {}

        name = (
            page.get("og_site_name")
            or page.get("app_name")
            or page.get("title", "").split("|")[0].split("–")[0].split("-")[0].strip()
            or domain
        )
        description = page.get("description", "")
        if len(description) > 400:
            description = description[:400].rsplit(" ", 1)[0] + "…"

        return {
            "name":        name[:120].strip(),
            "domain":      domain,
            "description": description,
            "website_url": f"https://{domain}",
            "country":     page.get("geo_country") or page.get("og_country") or "",
            "phone":       self._extract_phone(page.get("body_text", "")),
            "industry":    self._guess_industry_from_text(
                               description + " " + page.get("title", "")
                           ),
            "source":      "web_scrape",
            "mock":        False,
        }

    # ── PUBLIC: Google search snippet ────────────────────────────────────────

    def scrape_google_for_org(self, org_name: str) -> dict:
        """
        Search Google for '<org_name> company' and extract the first
        knowledge-panel description or search-result snippet.
        Returns {} on failure or if nothing useful found.
        """
        if not org_name or len(org_name) < 3:
            return {}

        panel = self._scrape_knowledge_panel(org_name, "")
        if panel:
            return {
                "name":        org_name,
                "description": panel.get("description", ""),
                "website_url": panel.get("website_url", ""),
                "source":      "google_scrape",
                "mock":        False,
            }
        return {}

    # ── PRIVATE: page fetcher ─────────────────────────────────────────────────

    def _scrape_page(self, url: str) -> dict:
        """
        Fetch a single URL and return parsed data dict.
        Returns {} on failure.
        """
        try:
            resp = requests.get(
                url,
                headers=_BROWSER_HEADERS,
                timeout=self.REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            if resp.status_code not in (200, 301, 302):
                return {}

            parser = _FullPageParser()
            parser.feed(resp.text)
            metas = parser.metas
            body_text = parser.get_body_text()

            return {
                "title":       parser.title.strip(),
                "og_site_name": metas.get("og:site_name", ""),
                "app_name":    metas.get("application-name", ""),
                "description": (
                    metas.get("og:description")
                    or metas.get("description")
                    or metas.get("twitter:description")
                    or ""
                ),
                "geo_country": metas.get("geo.country", ""),
                "og_country":  metas.get("og:country-name", ""),
                "links":       parser.links,
                "body_text":   body_text,
            }
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching {url}")
            return {}
        except Exception as e:
            logger.debug(f"Error fetching {url}: {e}")
            return {}

    def _scrape_subpage(self, domain: str, candidate_paths: list) -> dict:
        """
        Try each path in candidate_paths and return parsed data for the first
        one that returns a non-empty 200 response.
        """
        base_url = f"https://{domain}"
        for path in candidate_paths:
            url = base_url + path
            data = self._scrape_page(url)
            if data and len(data.get("body_text", "")) > 100:
                logger.debug(f"[deep_scrape] Subpage hit: {url}")
                return data
        return {}

    # ── PRIVATE: Google Knowledge Panel scraper ───────────────────────────────

    def _scrape_knowledge_panel(self, org_name: str, domain: str) -> dict:
        """
        Query Google for '<org_name> company' and extract structured data:
        description, founded year, headquarters, employee count, LinkedIn URL,
        and the official website URL.
        """
        query = f"{org_name} company" + (f" {domain}" if domain else "")
        try:
            time.sleep(random.uniform(0.8, 1.8))   # polite delay
            resp = requests.get(
                self.GOOGLE_SEARCH_URL,
                params={"q": query, "hl": "en", "gl": "us", "num": "5"},
                headers=_BROWSER_HEADERS,
                timeout=self.REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                return {}

            html = resp.text
            result: dict = {}

            # Description from knowledge panel or first snippet
            desc = self._extract_google_snippet(html)
            if desc:
                result["description"] = desc

            # Official website URL (first organic result)
            website = self._extract_first_result_url(html)
            if website:
                result["website_url"] = website

            # Founded year from knowledge panel facts
            founded = self._extract_founded_year(html)
            if founded:
                result["founded_year"] = founded

            # Headquarters / location
            hq_match = re.search(
                r"Headquarters?\s*[:\-]?\s*([A-Z][^\n<]{3,60})", html
            )
            if hq_match:
                hq_raw = re.sub(r"<[^>]+>", "", hq_match.group(1)).strip()
                parts = [p.strip() for p in re.split(r"[,;]", hq_raw) if p.strip()]
                if parts:
                    result["city"] = parts[0]
                    result["country"] = parts[-1] if len(parts) > 1 else ""

            # Employee count
            emp = self._extract_employee_range(html)
            if emp:
                result["employee_range"] = emp

            # Phone from knowledge panel
            phone = self._extract_phone(html)
            if phone:
                result["phone"] = phone

            # LinkedIn from links in the page
            linkedin_match = _LINKEDIN_RE.search(html)
            if linkedin_match:
                result["linkedin_url"] = linkedin_match.group(0)

            return result

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on Google search for '{org_name}'")
            return {}
        except Exception as e:
            logger.debug(f"Google panel error for '{org_name}': {e}")
            return {}

    # ── PRIVATE: field extractors ─────────────────────────────────────────────

    def _extract_phone(self, text: str) -> str:
        """Extract first phone number from free text (excludes IP addresses)."""
        if not text:
            return ""
        m = _PHONE_RE.search(text)
        if m:
            raw = m.group(1).strip()
            digits_only = re.sub(r"\D", "", raw)
            # Must have at least 7 digits
            if len(digits_only) < 7:
                return ""
            # Reject if it looks like an IPv4 address (e.g. 192.168.1.1)
            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", raw.strip()):
                return ""
            return raw
        return ""

    def _extract_location(self, text: str) -> tuple:
        """
        Returns (city, state, country) extracted from free text.
        Uses heuristic address-line parsing.
        """
        if not text:
            return ("", "", "")

        # Look for patterns like "City, State" or "City, Country"
        city = state = country = ""
        m = _ADDRESS_CITY_RE.search(text)
        if m:
            city = m.group(1).strip()
            second = m.group(2).strip()
            # If 2-letter uppercase → state/country code
            if len(second) == 2 and second.isupper():
                state = second
            else:
                country = second

        # Try to detect country names explicitly
        known_countries = [
            "India", "United States", "USA", "United Kingdom", "UK",
            "Germany", "France", "Netherlands", "Singapore", "Australia",
            "Canada", "Japan", "China", "UAE", "Brazil",
        ]
        for c in known_countries:
            if c in text:
                country = c
                break

        return (city, state, country)

    def _extract_employee_range(self, text: str) -> str:
        """Extract employee count/range from free text."""
        if not text:
            return ""
        for pattern in _EMPLOYEE_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                raw = m.group(1).replace(",", "")
                # Bucket into standard ranges
                try:
                    n = int(raw.replace("+", "").split("-")[0])
                    if n < 10:        return "1-10"
                    elif n < 50:      return "11-50"
                    elif n < 200:     return "51-200"
                    elif n < 500:     return "201-500"
                    elif n < 1000:    return "501-1000"
                    elif n < 5000:    return "1001-5000"
                    elif n < 10000:   return "5001-10000"
                    else:             return "10000+"
                except ValueError:
                    return raw  # return raw range string if not parseable
        return ""

    def _extract_founded_year(self, text: str) -> Optional[int]:
        """Extract founding year from free text."""
        if not text:
            return None
        for pattern in _FOUNDED_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                try:
                    year = int(m.group(1))
                    if 1800 <= year <= 2024:
                        return year
                except ValueError:
                    pass
        return None

    def _extract_linkedin(self, links: list) -> str:
        """Find a LinkedIn company URL in a list of hrefs."""
        for href in links:
            if "linkedin.com/company" in href:
                m = _LINKEDIN_RE.search(href)
                if m:
                    return m.group(0)
        return ""

    def _extract_google_snippet(self, html: str) -> str:
        """Pull first descriptive snippet from Google results HTML."""
        patterns = [
            r'<span[^>]*>\s*([A-Z][^<]{40,400})\s*</span>',
            r'class="[^"]*VwiC3b[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>',
            r'data-snf[^>]*>\s*<div[^>]*>(.*?)</div>',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.DOTALL)
            if m:
                raw = m.group(1)
                clean = re.sub(r"<[^>]+>", "", raw).strip()
                clean = re.sub(r"\s+", " ", clean)
                if len(clean) > 30:
                    return clean[:400]
        return ""

    def _extract_first_result_url(self, html: str) -> str:
        """Extract URL of the first organic Google result."""
        m = re.search(r'/url\?q=(https?://[^&"]+)', html)
        if m:
            url = requests.utils.unquote(m.group(1))
            if "google.com" not in url:
                return url
        return ""

    def _guess_industry_from_text(self, text: str) -> str:
        """Keyword-based industry classifier from free text."""
        text_lower = text.lower()
        for industry, kws in _INDUSTRY_MAP.items():
            if any(kw in text_lower for kw in kws):
                return industry
        return ""
