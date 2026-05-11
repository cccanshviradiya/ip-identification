# Mediya IP Intel — IP-Based Company Identification Platform

> **MVP/POC** | Indian B2B Traffic Intelligence | FastAPI + IPinfo + Apollo.io

---

## Overview

This platform identifies the company behind a visiting IP address using a multi-step enrichment pipeline:

```
IP Address
   ↓
[IPinfo Lookup]      → org, hostname, country, ASN
   ↓
[Classification]     → corporate / isp / hosting / vpn
   ↓ (reject if not corporate)
[Reverse DNS]        → PTR hostname (e.g. mail.infosys.com)
   ↓
[Domain Extraction]  → root domain (e.g. infosys.com)
   ↓
[Domain Validation]  → MX records + WHOIS age check
   ↓
[Apollo Enrichment]  → company name, industry, employees, LinkedIn
   ↓
[Structured JSON Response + SQLite Log]
```

---

## Tech Stack

| Layer       | Technology                               |
|-------------|------------------------------------------|
| Backend     | Python 3.11+, FastAPI, Uvicorn           |
| IP Lookup   | IPinfo.io API                            |
| Classification | Keyword matching (ISP/VPN/Hosting lists) |
| Reverse DNS | Python `socket` library                  |
| Validation  | `dnspython` (MX check) + `python-whois` |
| Enrichment  | Apollo.io Organization Enrichment API   |
| Storage     | SQLite via SQLAlchemy ORM               |
| Frontend    | Plain HTML + Vanilla CSS + Fetch API    |

---

## Folder Structure

```
mediya-ip-poc/
├── app/
│   ├── main.py                    ← FastAPI entry point
│   ├── config.py                  ← API keys + classification rules
│   ├── services/
│   │   ├── ip_lookup.py           ← IPinfo.io integration
│   │   ├── classifier.py          ← IP type classifier
│   │   ├── reverse_dns.py         ← PTR record lookup
│   │   ├── domain_extractor.py    ← Root domain extraction
│   │   ├── validator.py           ← MX + WHOIS age validation
│   │   ├── apollo_enrichment.py   ← Apollo.io enrichment + mock
│   │   └── logger.py              ← SQLite + JSONL logging
│   ├── routes/
│   │   └── identify.py            ← /api/identify/{ip} endpoint
│   ├── database/
│   │   └── models.py              ← SQLAlchemy ORM models
│   └── utils/
│       └── helpers.py             ← IP validation, domain sanitizer
├── frontend/
│   ├── index.html                 ← Main UI
│   ├── style.css                  ← Premium dark theme
│   └── app.js                     ← Fetch API + result rendering
├── logs/                          ← Auto-created: SQLite DB + JSONL logs
├── .env.example                   ← API key template
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Clone & Setup

```bash
cd "ip identification"
```

### 2. Create Virtual Environment

```bash
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # macOS/Linux
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure API Keys

```bash
copy .env.example .env
```

Edit `.env`:

```env
IPINFO_TOKEN=your_ipinfo_token_here
APOLLO_API_KEY=your_apollo_api_key_here
```

**Get free API keys:**
- IPinfo: https://ipinfo.io/signup (50,000 req/month free)
- Apollo: https://app.apollo.io/#/settings/integrations/api (free tier available)

### 5. Run the Server

```bash
cd app
python main.py
```

Or with uvicorn directly:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Open the Frontend

- **Web UI:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## API Reference

### `GET /api/identify/{ip}`

Runs the full identification pipeline for an IP address.

**Example:**
```bash
curl http://localhost:8000/api/identify/103.21.244.1
```

**Response (identified):**
```json
{
  "ip": "103.21.244.1",
  "status": "identified",
  "classification": "corporate",
  "org": "AS55836 Reliance Jio Infocomm Limited",
  "hostname": "mail.infosys.com",
  "domain": "infosys.com",
  "validated": true,
  "validation_reason": "All validation checks passed",
  "company": {
    "name": "Infosys",
    "industry": "Information Technology & Services",
    "employee_count": 300000,
    "revenue_range": ">$1B",
    "linkedin_url": "https://linkedin.com/company/infosys",
    "source": "apollo",
    "mock": false
  },
  "ipinfo": {
    "city": "Bangalore",
    "region": "Karnataka",
    "country": "IN",
    "asn": "AS12345"
  }
}
```

**Response (rejected ISP):**
```json
{
  "ip": "49.36.0.1",
  "status": "rejected",
  "classification": "isp",
  "reason": "Keyword match: ISP provider in org='as55836 reliance jio infocomm'",
  "hostname": null,
  "domain": null,
  "validated": false,
  "company": null
}
```

### `GET /api/logs/recent?limit=20`

Returns the most recent identification logs from SQLite.

### `GET /health`

Liveness probe — returns `{"status": "healthy"}`.

---

## Sample Test IPs

| IP              | Expected Classification | Company         |
|-----------------|------------------------|-----------------|
| `103.21.244.1`  | Corporate              | Infosys         |
| `202.131.90.100`| Corporate              | TCS / TATA      |
| `125.16.8.82`   | Corporate              | Wipro           |
| `8.8.8.8`       | Hosting → Rejected     | Google DNS      |
| `49.36.0.1`     | ISP → Rejected         | Reliance Jio    |
| `3.110.10.1`    | Hosting → Rejected     | AWS Mumbai      |
| `103.86.96.100` | VPN → Rejected         | NordVPN         |

---

## MVP Limitations (By Design)

1. **No authentication** — all endpoints are public
2. **No rate limiting** — not intended for production load
3. **Classification accuracy** depends on IPinfo's free tier data
4. **Apollo mock fallback** activates when API key is missing or domain not in Apollo DB
5. **Reverse DNS** is often not configured by Indian ISPs even for corporate IPs
6. **WHOIS** can be blocked or return inconsistent data

---

## Logs

After running, check:
- `logs/app.log` — application debug logs
- `logs/pipeline_results.jsonl` — one JSON record per request
- `logs/ip_identification.db` — SQLite database (open with DB Browser for SQLite)

---

## Architecture Notes

```
FastAPI App
└── /api/identify/{ip}
    ├── IPLookupService      → IPinfo.io
    ├── IPClassifier         → keyword matching
    ├── ReverseDNSService    → socket.gethostbyaddr
    ├── DomainExtractorService → regex/parsing
    ├── DomainValidatorService → dnspython + whois
    ├── ApolloEnrichmentService → Apollo.io REST API
    └── PipelineLogger       → SQLite + JSONL
```

All services are **stateless classes** — no shared mutable state between requests.

---

*Built as a clean MVP/POC — not intended for production deployment.*
