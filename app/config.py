"""
config.py — Central configuration loader for the IP Identification MVP.
Reads all settings from the .env file using python-dotenv.
"""

import os
from dotenv import load_dotenv

from pathlib import Path

# Load environment variables from .env file in the project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# ─── API Keys ────────────────────────────────────────────────────────────────
IPINFO_TOKEN: str = os.getenv("IPINFO_TOKEN", "")
APOLLO_API_KEY: str = os.getenv("APOLLO_API_KEY", "")

# ─── App Settings ────────────────────────────────────────────────────────────
APP_ENV: str = os.getenv("APP_ENV", "development")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG")

# ─── Database ────────────────────────────────────────────────────────────────
# Vercel's serverless functions have a read-only filesystem except for /tmp
# Check multiple Vercel environment variables to be safe (build & runtime)
if os.getenv("VERCEL") == "1" or os.getenv("VERCEL_ENV") or os.getenv("VERCEL_URL") or os.getenv("AWS_EXECUTION_ENV"):
    DATABASE_URL: str = "sqlite:////tmp/ip_identification.db"
else:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./logs/ip_identification.db")

# ─── Classification Rules ────────────────────────────────────────────────────
# Keywords to detect ISP/Residential providers (primarily Indian ISPs)
ISP_KEYWORDS = [
    "jio", "reliance", "airtel", "bsnl", "vodafone", "vi ", "idea",
    "hathway", "act fibernet", "you broadband", "sify", "tata sky", "tata play",
    "tikona", "spectranet", "atria", "excitel", "den networks", "alliance broadband",
    "gtpl", "k broadband", "m-connect", "netplus", "railwire", "wishnet",
    "comcast", "verizon", "at&t", "spectrum", "cox", "telekom", "orange", "telefonica",
]

# Keywords to detect Cloud/Hosting providers
HOSTING_KEYWORDS = [
    "amazon", "aws", "google", "gcp", "microsoft", "azure", "cloudflare",
    "digitalocean", "linode", "vultr", "ovh", "hetzner", "hostinger",
    "godaddy", "bluehost", "namecheap", "rackspace", "fastly", "akamai",
    "alibaba", "tencent", "oracle cloud", "ibm cloud", "liquid web",
    "contabo", "interserver", "siteground", "wp engine", "pantry",
]

# Keywords to detect VPN/Proxy providers
VPN_KEYWORDS = [
    "nordvpn", "expressvpn", "surfshark", "cyberghost", "mullvad",
    "protonvpn", "ipvanish", "hotspot shield", "hidemyass", "private internet",
    "vpn", "proxy", "anonymizer", "tor exit", "tunnelbear", "windscribe",
    "strongvpn", "vyprvpn", "purevpn", "zenmate",
]

# Mapping common organization names to their official business domains
# Useful when Reverse DNS (PTR) is missing for corporate IPs.
CORPORATE_DOMAIN_MAP = {
    "infosys": "infosys.com",
    "tata consultancy services": "tcs.com",
    "tata communications": "tatacommunications.com",
    "wipro": "wipro.com",
    "hcl technologies": "hcltech.com",
    "reliance industries": "ril.com",
    "reliance jio": "jio.com",
    "mahindra": "mahindra.com",
    "larsen & toubro": "larsentoubro.com",
    "icici bank": "icicibank.com",
    "hdfc bank": "hdfcbank.com",
    "state bank of india": "sbi.co.in",
    "tech mahindra": "techmahindra.com",
    "asml": "asml.com",
    "philips": "philips.com",
    "ing bank": "ing.com",
    "surf b.v.": "surf.nl",
    "joyent": "joyent.com",
}

# Generic TLDs/domains to skip during domain extraction
GENERIC_DOMAINS_BLACKLIST = [
    "in-addr.arpa", "amazonaws.com", "googleusercontent.com",
    "azure.com", "cloudfront.net", "akamaitechnologies.com",
    "cloudflare.com", "fastly.net",
]
