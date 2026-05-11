/**
 * app.js — Frontend logic for the Mediya IP Intel platform.
 * Uses the Fetch API to call the FastAPI backend and renders results dynamically.
 */

// ── Configuration ──────────────────────────────────────────────────────────────
const API_BASE = window.location.origin;  // Assumes frontend served from same origin

// ── DOM References ─────────────────────────────────────────────────────────────
const ipInput         = document.getElementById("ip-input");
const identifyBtn     = document.getElementById("identify-btn");
const loadingSection  = document.getElementById("loading-section");
const resultSection   = document.getElementById("result-section");
const errorSection    = document.getElementById("error-section");

// Pipeline step elements (for animated loading state)
const PIPELINE_STEPS = [
  "step-lookup",
  "step-classify",
  "step-rdns",
  "step-domain",
  "step-validate",
  "step-enrich",
];

// ── Allow pressing Enter in the input field ────────────────────────────────────
ipInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") identifyIP();
});

// ── Helper: fill input with a sample IP and trigger lookup ────────────────────
function useIP(ip) {
  ipInput.value = ip;
  ipInput.focus();
  identifyIP();
}

// ── Main identification function ──────────────────────────────────────────────
async function identifyIP() {
  const ip = ipInput.value.trim();

  if (!ip) {
    ipInput.focus();
    ipInput.classList.add("shake");
    setTimeout(() => ipInput.classList.remove("shake"), 500);
    return;
  }

  // Basic client-side IPv4 format check
  // Support both single IP and CIDR notation (e.g. 1.2.3.4 or 1.2.3.0/24)
  const ipv4Regex = /^(\d{1,3}\.){3}\d{1,3}(\/\d{1,2})?$/;
  if (!ipv4Regex.test(ip)) {
    showError("Invalid IP Format", `"${ip}" doesn't look like a valid IPv4 address. Please enter a valid public IP.`);
    return;
  }

  // Show loading state
  showLoading();

  try {
    // Animate steps in sequence while waiting for API response
    const stepAnimInterval = animateSteps();

    // Add a timestamp to prevent browser caching
    const cacheBuster = `?t=${Date.now()}`;
    const response = await fetch(`${API_BASE}/api/identify/${encodeURIComponent(ip)}${cacheBuster}`);

    clearInterval(stepAnimInterval);

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();

    // Mark all steps as done
    PIPELINE_STEPS.forEach(id => markStep(id, "done"));

    // Small delay to show completed steps before rendering result
    setTimeout(() => renderResult(data), 600);

  } catch (err) {
    console.error("Identification error:", err);
    showError("Request Failed", err.message || "Could not reach the backend API. Is the server running?");
  }
}

// ── Animate pipeline steps progressively ─────────────────────────────────────
function animateSteps() {
  let current = 0;
  PIPELINE_STEPS.forEach(id => markStep(id, "pending"));
  markStep(PIPELINE_STEPS[0], "active");

  const interval = setInterval(() => {
    if (current < PIPELINE_STEPS.length - 1) {
      markStep(PIPELINE_STEPS[current], "done");
      current++;
      markStep(PIPELINE_STEPS[current], "active");
    }
  }, 700);

  return interval;
}

function markStep(stepId, state) {
  const el = document.getElementById(stepId);
  if (!el) return;

  // Remove all state classes
  el.classList.remove("active", "done", "failed");

  // Replace the indicator element (spinner/dot/check/x)
  const indicator = el.querySelector(".step-spinner, .step-dot, .step-check, .step-x");
  if (indicator) indicator.remove();

  const newIndicator = document.createElement("div");

  if (state === "active") {
    el.classList.add("active");
    newIndicator.className = "step-spinner";
  } else if (state === "done") {
    el.classList.add("done");
    newIndicator.className = "step-check";
    newIndicator.textContent = "✓";
  } else if (state === "failed") {
    el.classList.add("failed");
    newIndicator.className = "step-x";
    newIndicator.textContent = "✗";
  } else {
    newIndicator.className = "step-dot";
  }

  el.insertBefore(newIndicator, el.firstChild);
}

// ── Render the final result card ──────────────────────────────────────────────
function renderResult(data) {
  hideAll();
  resultSection.style.display = "block";

  // ── Status Banner ──────────────────────────────────────────────────────────
  const statusBar   = document.getElementById("result-status-bar");
  const statusIcon  = document.getElementById("status-icon");
  const statusLabel = document.getElementById("status-label");
  const statusDetail = document.getElementById("status-detail");
  const classBadge  = document.getElementById("classification-badge");

  const status = data.status || "unknown";
  const classification = data.classification || "unknown";

  // Configure status banner appearance
  statusBar.className = "result-status-bar";
  statusIcon.className = "status-icon";

  const statusConfig = {
    identified: {
      label: "✓ Company Identified",
      detail: `Successfully enriched: ${data.company?.name || data.domain}`,
      barClass: "status-identified",
      iconClass: "icon-success",
      icon: "🏢",
    },
    identified_via_scrape: {
      label: "✓ Company Identified via Scraping",
      detail: `Enriched by web scraping: ${data.company?.name || data.domain || data.org}`,
      barClass: "status-identified",
      iconClass: "icon-success",
      icon: "🔎",
    },
    rejected: {
      label: "✗ IP Rejected",
      detail: data.reason || `Classified as ${classification} — not a corporate IP`,
      barClass: "status-rejected",
      iconClass: "icon-reject",
      icon: "🚫",
    },
    no_domain: {
      label: "⚠ No Domain Found",
      detail: "Could not extract a domain from reverse DNS or org",
      barClass: "status-no-domain",
      iconClass: "icon-warn",
      icon: "🔍",
    },
    invalid_domain: {
      label: "⚠ Domain Validation Failed",
      detail: data.validation_reason || "Domain failed MX or age checks",
      barClass: "status-invalid",
      iconClass: "icon-warn",
      icon: "⚠️",
    },
    partial: {
      label: "⚠ Partial Identification",
      detail: `Identified by network name: ${data.company?.name || data.org || "Unknown"}`,
      barClass: "status-no-domain",
      iconClass: "icon-warn",
      icon: "🔍",
    },
    private_ip: {
      label: "🔒 Private / Internal IP Address",
      detail: `${data.private_range || "Private range"} — not visible on the public internet`,
      barClass: "status-private",
      iconClass: "icon-private",
      icon: "🔒",
    },
  };

  const cfg = statusConfig[status] || {
    label: `Status: ${status}`,
    detail: "",
    barClass: "",
    iconClass: "icon-warn",
    icon: "❓",
  };

  statusBar.classList.add(cfg.barClass);
  statusIcon.classList.add(cfg.iconClass);
  statusIcon.textContent = cfg.icon;
  statusLabel.textContent = cfg.label;
  statusDetail.textContent = cfg.detail;

  // Classification badge
  classBadge.textContent = classification;
  classBadge.className = `classification-badge badge-${classification}`;

  // ── Network Info Block ─────────────────────────────────────────────────────
  const networkInfo = document.getElementById("network-info");
  networkInfo.innerHTML = "";

  // Special rendering for private IPs
  if (status === "private_ip") {
    renderPrivateIPGuidance(data, networkInfo);
    document.getElementById("company-info").innerHTML = "";
    const hint = document.createElement("p");
    hint.className = "info-value empty";
    hint.textContent = "Company lookup is not possible for private/internal IP addresses.";
    document.getElementById("company-info").appendChild(hint);
    document.getElementById("json-output").textContent = JSON.stringify(data, null, 2);
    document.getElementById("json-container").style.display = "none";
    document.getElementById("json-toggle-btn").textContent = "{ } View Raw JSON";
    return;
  }

  const ipinfoLoc = data.ipinfo || {};

  const networkRows = [
    { key: "IP Address", value: data.ip, cls: "mono" },
    { key: "Organization", value: data.org || "—" },
    { key: "Hostname (PTR)", value: data.hostname || "— (no PTR record)" },
    { key: "Domain", value: data.domain || "—", cls: "mono" },
    { key: "Validation", value: data.validated ? "✓ Passed" : "✗ Not validated", cls: data.validated ? "validated" : "not-validated" },
    { key: "Location", value: [ipinfoLoc.city, ipinfoLoc.region, ipinfoLoc.country].filter(Boolean).join(", ") || "—" },
    { key: "ASN", value: ipinfoLoc.asn || "—", cls: "mono" },
  ];

  networkRows.forEach(row => networkInfo.appendChild(createInfoRow(row.key, row.value, row.cls)));

  // ── Company Info Block ─────────────────────────────────────────────────────
  const companyInfo = document.getElementById("company-info");
  companyInfo.innerHTML = "";

  if (data.company) {
    const c = data.company;

    if (c.mock) {
      companyInfo.appendChild(createInfoRow("Notice", "⚠ Mock data — configure Apollo API key for real enrichment", "mock-notice"));
    }

    const companyRows = [
      { key: "Company Name", value: c.name || "—" },
      { key: "Description", value: c.description || "—" },
      { key: "Industry", value: c.industry || "—" },
      { key: "Employees", value: c.employee_count ? c.employee_count.toLocaleString() : (c.employee_range && c.employee_range !== "Unknown" ? c.employee_range : "—") },
      { key: "Revenue Range", value: (c.revenue_range && c.revenue_range !== "Unknown") ? c.revenue_range : "—" },
      { key: "Founded", value: c.founded_year || "—" },
      { key: "City", value: c.city || "—" },
      { key: "State", value: c.state || "—" },
      { key: "Country", value: c.country || "—" },
      { key: "Phone", value: c.phone || "—" },
      { key: "Data Source", value: c.source || "—" },
      {
        key: "LinkedIn",
        value: c.linkedin_url || "—",
        cls: c.linkedin_url ? "link" : "",
        link: c.linkedin_url,
      },
      {
        key: "Website",
        value: c.website_url || (data.domain ? `https://${data.domain}` : "—"),
        cls: (c.website_url || data.domain) ? "link" : "",
        link: c.website_url || (data.domain ? `https://${data.domain}` : ""),
      },
    ];

    companyRows.forEach(row =>
      companyInfo.appendChild(createInfoRow(row.key, row.value, row.cls, row.link))
    );
  } else {
    const empty = document.createElement("p");
    empty.className = "info-value empty";
    empty.textContent = status === "rejected"
      ? "IP was rejected — no enrichment performed."
      : "Enrichment not available for this IP.";
    companyInfo.appendChild(empty);
  }

  // ── Raw JSON ───────────────────────────────────────────────────────────────
  document.getElementById("json-output").textContent = JSON.stringify(data, null, 2);
  document.getElementById("json-container").style.display = "none";
  document.getElementById("json-toggle-btn").textContent = "{ } View Raw JSON";
}

// ── Create an info row element ─────────────────────────────────────────────────
function createInfoRow(key, value, cls = "", link = "") {
  const row = document.createElement("div");
  row.className = "info-row";

  const keyEl = document.createElement("span");
  keyEl.className = "info-key";
  keyEl.textContent = key;

  const valEl = document.createElement("span");
  valEl.className = `info-value ${cls || ""}`.trim();

  if (link && cls === "link") {
    const a = document.createElement("a");
    a.href = link.startsWith("http") ? link : `https://${link}`;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = value;
    valEl.appendChild(a);
  } else {
    valEl.textContent = value || "—";
  }

  row.appendChild(keyEl);
  row.appendChild(valEl);
  return row;
}

// ── Toggle raw JSON viewer ─────────────────────────────────────────────────────
function toggleJSON() {
  const container = document.getElementById("json-container");
  const btn = document.getElementById("json-toggle-btn");
  const isVisible = container.style.display !== "none";
  container.style.display = isVisible ? "none" : "block";
  btn.innerHTML = isVisible
    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M16 18l6-6-6-6M8 6l-6 6 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg> { } View Raw JSON`
    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M16 18l6-6-6-6M8 6l-6 6 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg> Hide JSON`;
}

// ── UI State Management ────────────────────────────────────────────────────────
function showLoading() {
  hideAll();
  loadingSection.style.display = "block";
  identifyBtn.disabled = true;
  identifyBtn.querySelector(".btn-text").textContent = "Identifying...";
  PIPELINE_STEPS.forEach(id => markStep(id, "pending"));
  markStep(PIPELINE_STEPS[0], "active");
}

function showError(title, message) {
  hideAll();
  errorSection.style.display = "block";
  document.getElementById("error-title").textContent = title;
  document.getElementById("error-message").textContent = message;
}

function hideAll() {
  loadingSection.style.display = "none";
  resultSection.style.display = "none";
  errorSection.style.display = "none";
  
  // Reset result containers to avoid flickering old data
  document.getElementById("network-info").innerHTML = "";
  document.getElementById("company-info").innerHTML = "";
  document.getElementById("json-output").textContent = "";

  identifyBtn.disabled = false;
  identifyBtn.querySelector(".btn-text").textContent = "Identify Company";
}

function resetUI() {
  hideAll();
  ipInput.value = "";
  ipInput.focus();
}

// ── Private IP Guidance Card ───────────────────────────────────────────────────
function renderPrivateIPGuidance(data, container) {
  // Explanation rows
  const rows = [
    { key: "IP Entered",    value: data.ip },
    { key: "Range",         value: data.private_range || "Private / Reserved" },
    { key: "Why it fails",  value: "Private IPs only exist inside your local network. IPinfo, WHOIS, and reverse DNS cannot see them." },
    { key: "What to do",   value: data.how_to_find_public_ip || "Look up your public IP and use that instead." },
  ];
  rows.forEach(r => container.appendChild(createInfoRow(r.key, r.value)));

  // Auto-detect public IP button
  const btnWrap = document.createElement("div");
  btnWrap.style.cssText = "margin-top:16px;";

  const detectBtn = document.createElement("button");
  detectBtn.id = "detect-public-ip-btn";
  detectBtn.className = "identify-btn";
  detectBtn.style.cssText = "font-size:0.85rem; padding:10px 20px; width:auto;";
  detectBtn.innerHTML = `<span class="btn-text">🌐 Detect My Public IP &amp; Look Up</span>`;

  detectBtn.onclick = async () => {
    detectBtn.disabled = true;
    detectBtn.querySelector(".btn-text").textContent = "Detecting...";
    try {
      const resp = await fetch("https://api.ipify.org?format=json", { timeout: 5000 });
      const { ip: publicIp } = await resp.json();
      ipInput.value = publicIp;
      detectBtn.querySelector(".btn-text").textContent = `Found: ${publicIp} — Looking up...`;
      setTimeout(() => identifyIP(), 400);
    } catch (e) {
      detectBtn.disabled = false;
      detectBtn.querySelector(".btn-text").textContent = "⚠ Could not detect. Try: whatismyipaddress.com";
    }
  };

  btnWrap.appendChild(detectBtn);

  // Also show a manual hint link
  const hint = document.createElement("p");
  hint.style.cssText = "margin-top:10px; font-size:0.8rem; opacity:0.6;";
  hint.innerHTML = `Or find it manually at <a href="https://whatismyipaddress.com" target="_blank" rel="noopener" style="color:#8b5cf6;">whatismyipaddress.com</a>`;
  btnWrap.appendChild(hint);

  container.appendChild(btnWrap);
}
