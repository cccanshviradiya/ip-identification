"""
identify.py — FastAPI router for the /identify/{ip} endpoint.
Orchestrates the full IP identification pipeline end-to-end.
"""

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from typing import Optional
import sys, os, ipaddress
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from services.ip_lookup import IPLookupService
from services.classifier import IPClassifier
from services.reverse_dns import ReverseDNSService
from services.domain_extractor import DomainExtractorService
from services.validator import DomainValidatorService
from services.apollo_enrichment import ApolloEnrichmentService
from services.web_scraper import WebScraperService
from services.logger import PipelineLogger, get_logger
from database.models import get_db
from utils.helpers import is_valid_ipv4, is_private_ip, sanitize_domain, build_rejection_response

router = APIRouter()
logger = get_logger("identify_route")

# ─── Service singletons (instantiated once per process) ────────────────────────
ip_lookup_svc = IPLookupService()
classifier_svc = IPClassifier()
reverse_dns_svc = ReverseDNSService()
domain_extractor_svc = DomainExtractorService()
validator_svc = DomainValidatorService()
apollo_svc = ApolloEnrichmentService()
scraper_svc = WebScraperService()
pipeline_logger = PipelineLogger()


@router.get("/identify/{ip:path}", summary="Identify company from IP address")
async def identify_ip(
    ip: str = Path(..., description="Public IPv4 address or CIDR block"),
    db: Session = Depends(get_db),
):
    """
    Full IP identification pipeline:

    1. Validate IP format
    2. Lookup metadata via IPinfo
    3. Classify IP (corporate/isp/hosting/vpn)
    4. Reject non-corporate IPs immediately
    5. Perform reverse DNS lookup
    6. Extract root domain
    7. Validate domain (MX records + age)
    8. Enrich with Apollo.io
    9. Log and return structured result
    """
    logger.info(f"▶ Received identification request for IP: {ip}")

    # ── Step 1: Validate IP format ─────────────────────────────────────────
    if not is_valid_ipv4(ip):
        raise HTTPException(
            status_code=400,
            detail=f"'{ip}' is not a valid public IPv4 address or CIDR block.",
        )

    # ── Step 1b: Detect private / reserved IP ranges ───────────────────────
    # Private IPs (RFC 1918) live only inside local networks and cannot be
    # looked up by any external API (IPinfo, WHOIS, reverse DNS, etc.).
    # We return a clear, helpful explanation instead of a confusing error.
    if is_private_ip(ip):
        try:
            addr = ipaddress.IPv4Address(ip.split("/")[0])
            if addr.is_loopback:
                range_name = "Loopback (127.0.0.0/8)"
                range_desc = "This address refers to the local machine itself."
            elif str(addr).startswith("10."):
                range_name = "Class A Private (10.0.0.0/8)"
                range_desc = "Used by large private networks (offices, campuses, data centers)."
            elif str(addr).startswith("192.168."):
                range_name = "Class C Private (192.168.0.0/16)"
                range_desc = "Commonly used by home routers and small office networks."
            elif addr.is_link_local:
                range_name = "Link-Local (169.254.0.0/16)"
                range_desc = "Auto-assigned when DHCP fails. Not routable beyond the local segment."
            else:
                range_name = "Class B Private (172.16.0.0/12)"
                range_desc = "Used by medium-sized private networks."
        except Exception:
            range_name = "Private / Reserved"
            range_desc = "This IP range is not routable on the public internet."

        logger.info(f"⚠ Private IP detected: {ip} ({range_name})")
        private_result = {
            "ip": ip,
            "status": "private_ip",
            "classification": "private",
            "reason": (
                f"{ip} is a {range_name} address. {range_desc} "
                "Private IPs are internal to your local network and cannot be "
                "identified by external services like IPinfo, WHOIS, or reverse DNS."
            ),
            "how_to_find_public_ip": (
                "To identify your organization, look up your PUBLIC IP instead. "
                "Your public IP is the one your ISP assigns to your router — "
                "it is visible to the internet. "
                "Find it at: https://api.ipify.org or https://whatismyipaddress.com"
            ),
            "private_range": range_name,
            "org": None,
            "hostname": None,
            "domain": None,
            "validated": False,
            "company": None,
            "ipinfo": None,
        }
        pipeline_logger.log_result(db, private_result)
        return private_result

    # If it's a CIDR, resolve to the network address for lookup
    lookup_ip = ip
    if "/" in ip:
        net = ipaddress.IPv4Network(ip, strict=False)
        lookup_ip = str(net.network_address)
        logger.info(f"CIDR input: {ip} -> Resolving to network address for lookup: {lookup_ip}")


    # ── Step 2: IPinfo lookup ──────────────────────────────────────────────
    logger.info(f"[1/6] Running IPinfo lookup for {lookup_ip}")
    ipinfo_data = ip_lookup_svc.lookup(lookup_ip)
    org = ipinfo_data.get("org", "")
    logger.debug(f"IPinfo result: org={org} | country={ipinfo_data.get('country')}")

    # ── Step 2b: Handle IPs where IPinfo has no org (small/unknown organization) ──
    # IPinfo only covers large ISPs and well-known companies. For small corporate
    # networks, org may be empty. We do a reverse DNS first to get the hostname,
    # then attempt a Google scrape using the domain extracted from the hostname.
    if not org:
        logger.info(
            f"IPinfo returned no org for {lookup_ip}. "
            "Will attempt reverse-DNS + domain scrape after classification."
        )

    # ── Step 3: Classify IP ────────────────────────────────────────────────
    logger.info(f"[2/6] Classifying IP")
    classification_result = classifier_svc.classify(ipinfo_data)
    classification = classification_result["classification"]
    should_process = classification_result["should_process"]
    class_reason = classification_result["reason"]
    logger.info(f"Classification: {classification} | Reason: {class_reason}")

    # ── Step 4: Reject non-corporate IPs immediately ──────────────────────
    if not should_process:
        logger.info(f"✗ IP {ip} rejected as {classification} ({class_reason})")
        
        final_result = {
            "ip": ip,
            "status": "rejected",
            "classification": classification,
            "reason": class_reason,
            "org": org,
            "hostname": None,
            "domain": None,
            "validated": False,
            "company": None,
            "ipinfo": {
                "city": ipinfo_data.get("city"),
                "region": ipinfo_data.get("region"),
                "country": ipinfo_data.get("country"),
                "asn": ipinfo_data.get("asn"),
            },
        }
        pipeline_logger.log_result(db, final_result)
        return final_result

    # ── Step 5: Reverse DNS ────────────────────────────────────────────────
    logger.info(f"[3/6] Performing reverse DNS lookup")
    rdns_result = reverse_dns_svc.lookup(lookup_ip)
    hostname = rdns_result.get("hostname", "")
    logger.debug(f"Hostname from PTR: '{hostname}'")

    # ── Step 6: Domain & Name extraction ──────────────────────────────────
    logger.info(f"[4/6] Extracting domain/name")
    domain = ""
    clean_name = domain_extractor_svc.clean_org_name(org)

    # Try hostname first (most reliable)
    if hostname:
        domain = domain_extractor_svc.extract_from_hostname(hostname)

    # Fall back to IPinfo org string for domain
    if not domain and org:
        domain = domain_extractor_svc.extract_from_org(org)

    # NEW: Fallback to corporate domain map if still no domain
    if not domain and clean_name:
        domain = domain_extractor_svc.map_name_to_domain(clean_name)

    domain = sanitize_domain(domain)
    logger.info(f"Extracted domain: '{domain}' | Clean name: '{clean_name}'")

    # ── Step 7: Domain validation ──────────────────────────────────────────
    is_valid = False
    validation_reason = "No domain to validate"
    
    if domain:
        logger.info(f"[5/6] Validating domain: {domain}")
        validation_result = validator_svc.validate(domain)
        is_valid = validation_result["valid"]
        validation_reason = validation_result["reason"]
        logger.info(f"Validation: valid={is_valid} | reason={validation_reason}")

    # ── Step 8: Apollo enrichment (with scrape fallback built-in) ─────────
    company_data = None
    if is_valid:
        logger.info(f"[6/6] Enriching domain via Apollo (+scrape fallback): {domain}")
        company_data = apollo_svc.enrich(domain, company_name=clean_name)
    elif clean_name:
        logger.info(f"[6/6] No valid domain, using clean name for fallback: {clean_name}")
        company_data = apollo_svc.enrich("", company_name=clean_name)
    elif not org and hostname:
        # IPinfo had no org at all — try to scrape using the hostname domain
        hostname_domain = sanitize_domain(
            domain_extractor_svc.extract_from_hostname(hostname)
        )
        if hostname_domain:
            logger.info(
                f"[6/6] IPinfo org missing. Scraping hostname domain: {hostname_domain}"
            )
            scraped = scraper_svc.scrape_company_website(hostname_domain)
            if scraped:
                company_data = {
                    "name": scraped.get("name") or hostname_domain,
                    "domain": hostname_domain,
                    "industry": scraped.get("industry") or "Unknown",
                    "sub_industry": [],
                    "employee_count": None,
                    "employee_range": "Unknown",
                    "revenue_range": "Unknown",
                    "founded_year": None,
                    "description": scraped.get("description") or "",
                    "linkedin_url": "",
                    "website_url": scraped.get("website_url") or f"https://{hostname_domain}",
                    "phone": scraped.get("phone") or "",
                    "city": "",
                    "state": "",
                    "country": scraped.get("country") or "",
                    "source": scraped.get("source", "web_scrape"),
                    "mock": False,
                    "scrape_fallback": True,
                }

    # ── Step 9: Patch partial results via deep scraping ────────────────────
    # Fires whenever:
    #   • company_data is None (no enrichment at all)
    #   • company_data["mock"] is True (Apollo + all strategies failed)
    #   • Key fields are missing (name/description/industry/city all empty)
    needs_scrape_patch = (
        company_data is None
        or company_data.get("mock") is True
        or not any([
            company_data.get("description"),
            company_data.get("industry"),
            company_data.get("city"),
            company_data.get("founded_year"),
        ])
    )

    if needs_scrape_patch:
        # Determine the best domain to scrape against
        scrape_domain = domain or (
            sanitize_domain(domain_extractor_svc.extract_from_hostname(hostname))
            if hostname else ""
        )
        scrape_name = clean_name or org

        if scrape_domain or scrape_name:
            logger.info(
                f"[9/9] Partial result detected — running deep-scrape patch. "
                f"domain='{scrape_domain}' name='{scrape_name}'"
            )

            if company_data is None:
                # Build a minimal shell to patch into
                company_data = {
                    "name": scrape_name or scrape_domain or "Unknown",
                    "domain": scrape_domain,
                    "description": "",
                    "industry": "",
                    "sub_industry": [],
                    "employee_count": None,
                    "employee_range": "Unknown",
                    "revenue_range": "Unknown",
                    "founded_year": None,
                    "linkedin_url": "",
                    "website_url": f"https://{scrape_domain}" if scrape_domain else "",
                    "phone": "",
                    "city": "",
                    "state": "",
                    "country": "",
                    "source": "mock",
                    "mock": True,
                }

            # Run deep scrape with a 20-second timeout to avoid hanging the API
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        apollo_svc.patch_partial_with_scrape,
                        company_data,
                        scrape_domain,
                        scrape_name,
                    )
                    company_data = future.result(timeout=20)
            except FuturesTimeout:
                logger.warning(
                    f"[9/9] Deep-scrape timed out after 20s for '{scrape_domain}'. "
                    "Returning whatever data is available."
                )
            except Exception as scrape_err:
                logger.error(f"[9/9] Deep-scrape patch error: {scrape_err}")
        else:
            logger.warning(
                f"[9/9] Cannot patch partial result — no domain or org name available."
            )

    # ── Step 10: Build final response ───────────────────────────────────────
    # Status logic:
    #   'identified'            — Apollo gave full data for a validated domain
    #   'identified_via_scrape' — Scraping filled the gaps (partial → complete)
    #   'partial'               — Some data found but key fields still empty

    if is_valid:
        status = "identified"
    elif (
        company_data
        and not company_data.get("mock")
        and company_data.get("name")
        and company_data.get("name") not in ("Unknown", "Unknown Company")
    ):
        status = "identified_via_scrape"
    else:
        status = "partial"

    final_result = {
        "ip": ip,
        "status": status,
        "classification": classification,
        "org": org,
        "hostname": hostname or None,
        "domain": domain or None,
        "validated": is_valid,
        "validation_reason": validation_reason,
        "company": company_data,
        "ipinfo": {
            "city": ipinfo_data.get("city"),
            "region": ipinfo_data.get("region"),
            "country": ipinfo_data.get("country"),
            "asn": ipinfo_data.get("asn"),
        },
    }

    pipeline_logger.log_result(db, final_result)
    logger.info(f"✓ Pipeline complete for IP {ip} → Status: {status}")

    return final_result


@router.get("/logs/recent", summary="Fetch recent pipeline logs")
async def get_recent_logs(limit: int = 20, db: Session = Depends(get_db)):
    """
    Return the most recent IP identification log entries from SQLite.
    Useful for debugging and reviewing pipeline results.
    """
    from database.models import IPLookupLog
    from sqlalchemy import desc

    logs = (
        db.query(IPLookupLog)
        .order_by(desc(IPLookupLog.created_at))
        .limit(limit)
        .all()
    )

    return [
        {
            "id": log.id,
            "ip": log.ip,
            "classification": log.classification,
            "org": log.org,
            "hostname": log.hostname,
            "domain": log.domain,
            "validated": log.validated,
            "status": log.status,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
