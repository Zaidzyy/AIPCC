"""Deterministic demo fixtures for `python -m app.db.seed --demo`.

A dashboard with three reports on it does not look like a security console; it
looks like a broken one. This module writes a realistic history — several weeks
of reports across two analysts, with varied severities, repeated attack
techniques and anomaly volume that moves — so a reviewer who clones the repo
sees the charts doing their job on the first run.

**No LLM is involved.** Every value below is fixture data, and the shuffling is
driven by a fixed-seed `random.Random`, so two runs of `--demo` on the same day
produce byte-identical rows. That matters for two reasons: a screenshot is
reproducible, and a bug in an aggregate query cannot hide behind data that
changed underneath it.

The only thing that moves between runs is the date window, which is anchored to
today so the charts are always populated up to the present.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import (
    Anomaly,
    AttackType,
    Document,
    Report,
    RiskAssessment,
    SecurityAlert,
    ThreatIntel,
    Timeline,
    Users,
    Vulnerability,
)
from app.services.integrity import hash_document

# Fixed so the fixture is reproducible. Any constant would do; this is the date
# the demo set was written.
SEED = 20260810

WINDOW_DAYS = 42
REPORTS_PER_OWNER = 22


# --- Source documents -----------------------------------------------------

DEMO_DOCUMENTS = [
    ("edge-firewall-2026-07.csv", "timestamp,src_ip,dst_ip,proto,action,bytes"),
    ("vpn-auth-audit.csv", "timestamp,user,src_ip,result,mfa,geo"),
    ("dns-egress-sample.csv", "timestamp,host,query,qtype,resolver,verdict"),
    ("endpoint-process-telemetry.csv", "timestamp,host,user,process,parent,cmdline"),
    ("web-proxy-access.csv", "timestamp,client,method,url,status,ua"),
]

_LOG_ROWS = [
    "2026-07-04T02:11:07Z,10.14.2.37,203.0.113.44,tcp,allow,148213",
    "2026-07-04T02:11:44Z,10.14.2.37,203.0.113.44,tcp,allow,982441",
    "2026-07-04T02:14:02Z,10.14.9.11,198.51.100.23,udp,deny,512",
    "2026-07-04T03:41:19Z,10.14.2.37,203.0.113.44,tcp,allow,2214880",
    "2026-07-04T04:02:55Z,172.16.5.90,192.0.2.17,tcp,deny,0",
]


# --- Finding libraries ----------------------------------------------------
#
# Each attack carries its own flat risk fields, matching `AttackType`'s columns
# — the prototype nested them and the two halves drifted (CLAUDE.md, Phase 1).

ATTACKS = [
    {
        "attack_name": "Brute Force",
        "attack_mitre_technique_id": "T1110",
        "attack_mitre_technique_name": "Brute Force",
        "attack_description": (
            "Sustained authentication attempts against the VPN concentrator from a "
            "single autonomous system, cycling a short password list across many "
            "valid usernames."
        ),
        "risk_name": "Credential compromise via password spraying",
        "risk_description": (
            "Lockout thresholds are per-account, so an attacker spraying one password "
            "across every account never trips them."
        ),
        "risk_level": "High",
        "impact": "Unauthorised remote access using legitimate credentials.",
        "likelihood": "High",
        "mitigation": "Enforce MFA on all VPN accounts and add source-IP rate limiting.",
    },
    {
        "attack_name": "Phishing",
        "attack_mitre_technique_id": "T1566",
        "attack_mitre_technique_name": "Phishing",
        "attack_description": (
            "Inbound mail carrying a look-alike domain and an HTML attachment that "
            "renders a credential-harvesting form locally."
        ),
        "risk_name": "Initial access through user-supplied credentials",
        "risk_description": "Local rendering defeats URL reputation scanning at the gateway.",
        "risk_level": "High",
        "impact": "Attacker obtains a working identity without touching the perimeter.",
        "likelihood": "Medium",
        "mitigation": "Strip active HTML attachments and alert on look-alike sender domains.",
    },
    {
        "attack_name": "Valid Accounts",
        "attack_mitre_technique_id": "T1078",
        "attack_mitre_technique_name": "Valid Accounts",
        "attack_description": (
            "A service account authenticated from a geography it has never been seen "
            "in, outside its scheduled window, and immediately enumerated shares."
        ),
        "risk_name": "Lateral movement using a non-human identity",
        "risk_description": (
            "The account holds standing domain rights and no interactive-logon "
            "restriction, so its use is indistinguishable from normal automation."
        ),
        "risk_level": "Critical",
        "impact": "Domain-wide access with no exploit and no malware to detect.",
        "likelihood": "Medium",
        "mitigation": "Deny interactive logon for service accounts and scope their rights.",
    },
    {
        "attack_name": "Exploit Public-Facing Application",
        "attack_mitre_technique_id": "T1190",
        "attack_mitre_technique_name": "Exploit Public-Facing Application",
        "attack_description": (
            "Crafted requests against the externally reachable reporting portal, "
            "matching a known deserialisation payload signature."
        ),
        "risk_name": "Remote code execution on a perimeter host",
        "risk_description": "The host sits in the DMZ but holds a database credential in its environment.",
        "risk_level": "Critical",
        "impact": "Code execution followed by direct database access.",
        "likelihood": "High",
        "mitigation": "Patch the affected component and move the credential to a secrets store.",
    },
    {
        "attack_name": "Command and Scripting Interpreter",
        "attack_mitre_technique_id": "T1059",
        "attack_mitre_technique_name": "Command and Scripting Interpreter",
        "attack_description": (
            "Encoded PowerShell launched by a document-handling parent process on "
            "four endpoints within eleven minutes."
        ),
        "risk_name": "Post-compromise execution",
        "risk_description": "Script block logging is off on the affected fleet, so the payload body is unrecoverable.",
        "risk_level": "High",
        "impact": "Arbitrary execution in the user's context with no forensic record.",
        "likelihood": "High",
        "mitigation": "Enable script block logging and constrained language mode.",
    },
    {
        "attack_name": "Exfiltration Over C2 Channel",
        "attack_mitre_technique_id": "T1041",
        "attack_mitre_technique_name": "Exfiltration Over C2 Channel",
        "attack_description": (
            "Steady 40 KB outbound bursts at a fixed 300-second interval to a host "
            "registered nine days ago."
        ),
        "risk_name": "Data leaving the estate over an established channel",
        "risk_description": "Beacon jitter is low enough to be periodic but the volume stays under egress alerting thresholds.",
        "risk_level": "Critical",
        "impact": "Sustained low-and-slow loss of data with no single alertable event.",
        "likelihood": "Medium",
        "mitigation": "Alert on periodicity rather than volume, and block newly registered domains.",
    },
    {
        "attack_name": "Data Encrypted for Impact",
        "attack_mitre_technique_id": "T1486",
        "attack_mitre_technique_name": "Data Encrypted for Impact",
        "attack_description": (
            "Mass rename activity across a file server, one extension, thousands of "
            "files, following a shadow-copy deletion."
        ),
        "risk_name": "Ransomware detonation",
        "risk_description": "Backups are on the same domain and reachable by the compromised account.",
        "risk_level": "Critical",
        "impact": "Loss of the primary share and of the backups intended to recover it.",
        "likelihood": "Low",
        "mitigation": "Move backups off-domain and alert on shadow-copy deletion.",
    },
    {
        "attack_name": "Network Service Discovery",
        "attack_mitre_technique_id": "T1046",
        "attack_mitre_technique_name": "Network Service Discovery",
        "attack_description": "Sequential connection attempts across 1 024 ports on a /24 from one internal host.",
        "risk_name": "Internal reconnaissance",
        "risk_description": "East-west traffic is unsegmented, so the scan completes without obstruction.",
        "risk_level": "Medium",
        "impact": "The attacker learns the internal service map before being noticed.",
        "likelihood": "High",
        "mitigation": "Segment east-west traffic and alert on horizontal port sweeps.",
    },
    {
        "attack_name": "OS Credential Dumping",
        "attack_mitre_technique_id": "T1003",
        "attack_mitre_technique_name": "OS Credential Dumping",
        "attack_description": "A handle opened against LSASS by a process running from a user-writable path.",
        "risk_name": "Credential theft from memory",
        "risk_description": "Cached domain credentials on the host include a privileged account.",
        "risk_level": "Critical",
        "impact": "Escalation from one endpoint to a privileged domain identity.",
        "likelihood": "Medium",
        "mitigation": "Enable LSA protection and restrict cached credential storage.",
    },
    {
        "attack_name": "Remote Services",
        "attack_mitre_technique_id": "T1021",
        "attack_mitre_technique_name": "Remote Services",
        "attack_description": "SMB sessions from one workstation to nineteen hosts inside four minutes.",
        "risk_name": "Lateral movement across the workstation estate",
        "risk_description": "Local administrator passwords are shared across the build, so one hash opens all of them.",
        "risk_level": "High",
        "impact": "Fleet-wide access from a single compromised endpoint.",
        "likelihood": "High",
        "mitigation": "Roll out per-host local administrator password randomisation.",
    },
    {
        "attack_name": "Ingress Tool Transfer",
        "attack_mitre_technique_id": "T1105",
        "attack_mitre_technique_name": "Ingress Tool Transfer",
        "attack_description": "A signed system binary retrieved an archive from a paste service and wrote it to a temp path.",
        "risk_name": "Tooling staged on a compromised host",
        "risk_description": "The download used a living-off-the-land binary, so application allow-listing did not fire.",
        "risk_level": "Medium",
        "impact": "Attacker tooling lands without tripping executable controls.",
        "likelihood": "Medium",
        "mitigation": "Block paste-service egress and monitor LOLBin network use.",
    },
    {
        "attack_name": "Gather Victim Host Information",
        "attack_mitre_technique_id": "T1592",
        "attack_mitre_technique_name": "Gather Victim Host Information",
        "attack_description": (
            "Repeated unauthenticated requests enumerating server banners and "
            "software versions across the public estate."
        ),
        "risk_name": "Passive fingerprinting of external services",
        "risk_description": "Version banners are served verbatim, so an attacker learns the patch level without authenticating.",
        "risk_level": "Low",
        "impact": "Reconnaissance value only; no direct access is gained.",
        "likelihood": "High",
        "mitigation": "Suppress version banners on internet-facing services.",
    },
    {
        "attack_name": "Web Service",
        "attack_mitre_technique_id": "T1102",
        "attack_mitre_technique_name": "Web Service",
        "attack_description": "Outbound traffic to a legitimate collaboration API at a cadence unusual for the host's role.",
        "risk_name": "Low-volume traffic to a permitted third party",
        "risk_description": "The destination is on the corporate allow list, so the traffic is indistinguishable from sanctioned use.",
        "risk_level": "Low",
        "impact": "A potential channel, but no payload or staged data was observed.",
        "likelihood": "Low",
        "mitigation": "Baseline per-role egress and alert on deviation rather than destination.",
    },
    {
        "attack_name": "Application Layer Protocol",
        "attack_mitre_technique_id": "T1071",
        "attack_mitre_technique_name": "Application Layer Protocol",
        "attack_description": "DNS TXT queries averaging 180 bytes of base32 payload to a single delegated zone.",
        "risk_name": "Covert channel over DNS",
        "risk_description": "Resolver logs are retained for 24 hours, which is shorter than the observed campaign.",
        "risk_level": "High",
        "impact": "Command and control that survives egress filtering.",
        "likelihood": "Medium",
        "mitigation": "Extend resolver log retention and alert on high-entropy subdomains.",
    },
]

GENERAL_RISKS = [
    {
        "risk_name": "Unsegmented internal network",
        "risk_description": "Workstation VLANs reach server VLANs on every port, so any endpoint compromise is a datacentre compromise.",
        "risk_level": "High",
        "impact": "One phished user reaches production directly.",
        "likelihood": "High",
        "mitigation": "Introduce east-west policy between workstation and server zones.",
    },
    {
        "risk_name": "MFA not enforced for remote access",
        "risk_description": "Roughly a fifth of VPN-entitled accounts have no second factor registered.",
        "risk_level": "Critical",
        "impact": "A single valid password is sufficient for remote access.",
        "likelihood": "High",
        "mitigation": "Make MFA a condition of the VPN entitlement rather than a user setting.",
    },
    {
        "risk_name": "Short log retention on resolvers",
        "risk_description": "DNS logs roll at 24 hours, below the dwell time seen in this dataset.",
        "risk_level": "Medium",
        "impact": "Investigations cannot reconstruct the beginning of an incident.",
        "likelihood": "Medium",
        "mitigation": "Retain resolver logs for 90 days and ship them centrally.",
    },
    {
        "risk_name": "Shared local administrator credential",
        "risk_description": "The workstation build ships one local administrator password across every host.",
        "risk_level": "High",
        "impact": "Pass-the-hash from any endpoint to all others.",
        "likelihood": "High",
        "mitigation": "Deploy per-host randomised local administrator passwords.",
    },
    {
        "risk_name": "Backups reachable from the production domain",
        "risk_description": "Backup shares authenticate against the same directory they protect.",
        "risk_level": "Critical",
        "impact": "Recovery media is encrypted alongside the primary data.",
        "likelihood": "Low",
        "mitigation": "Move backups to a separate trust boundary with immutable retention.",
    },
    {
        "risk_name": "Service accounts with standing privilege",
        "risk_description": "Eleven automation accounts hold permanent rights that are needed for minutes a day.",
        "risk_level": "Medium",
        "impact": "A stolen automation credential is immediately privileged.",
        "likelihood": "Medium",
        "mitigation": "Move automation to just-in-time elevation.",
    },
    {
        "risk_name": "Unpatched perimeter appliance",
        "risk_description": "The edge appliance is four firmware releases behind, two of them security releases.",
        "risk_level": "High",
        "impact": "Publicly documented exploit paths remain open at the perimeter.",
        "likelihood": "Medium",
        "mitigation": "Bring the appliance onto the vendor's current release train.",
    },
    {
        "risk_name": "No egress filtering from server subnets",
        "risk_description": "Servers may open arbitrary outbound connections on any port.",
        "risk_level": "Medium",
        "impact": "Command-and-control from a server needs no evasion.",
        "likelihood": "High",
        "mitigation": "Default-deny egress with an allow list per server role.",
    },
    {
        "risk_name": "Version banners exposed on public services",
        "risk_description": "Four internet-facing services return exact build numbers to unauthenticated requests.",
        "risk_level": "Low",
        "impact": "Reduces an attacker's reconnaissance effort; grants no access on its own.",
        "likelihood": "High",
        "mitigation": "Suppress version strings at the reverse proxy.",
    },
    {
        "risk_name": "Console session timeout longer than policy",
        "risk_description": "The management console idles for eight hours where policy specifies one.",
        "risk_level": "Low",
        "impact": "An unattended workstation stays authenticated well past the intended window.",
        "likelihood": "Medium",
        "mitigation": "Align the console timeout with the documented policy.",
    },
]

VULNERABILITIES = [
    {
        "vulnerability_name": "Log4j JNDI lookup in the reporting service",
        "vulnerability_description": "A bundled logging library resolves attacker-controlled JNDI URIs from logged strings.",
        "cve_id": "CVE-2021-44228",
        "cve_description": "Apache Log4j2 JNDI features do not protect against attacker-controlled LDAP endpoints.",
        "cwe_id": "CWE-502",
        "cwe_description": "Deserialization of untrusted data.",
    },
    {
        "vulnerability_name": "SMBv1 enabled on legacy file servers",
        "vulnerability_description": "Three file servers still answer SMBv1 negotiation.",
        "cve_id": "CVE-2017-0144",
        "cve_description": "Microsoft SMBv1 allows remote code execution via crafted packets.",
        "cwe_id": "CWE-20",
        "cwe_description": "Improper input validation.",
    },
    {
        "vulnerability_name": "OpenSSL heartbeat over-read on the load balancer",
        "vulnerability_description": "The management interface serves a TLS stack vulnerable to memory disclosure.",
        "cve_id": "CVE-2014-0160",
        "cve_description": "OpenSSL heartbeat extension allows remote attackers to read process memory.",
        "cwe_id": "CWE-125",
        "cwe_description": "Out-of-bounds read.",
    },
    {
        "vulnerability_name": "Heap overflow in the bundled image decoder",
        "vulnerability_description": "The document pipeline links a libwebp build predating the huffman-table fix.",
        "cve_id": "CVE-2023-4863",
        "cve_description": "Heap buffer overflow in libwebp allows out-of-bounds memory write.",
        "cwe_id": "CWE-787",
        "cwe_description": "Out-of-bounds write.",
    },
    {
        "vulnerability_name": "Path traversal in the SSL VPN portal",
        "vulnerability_description": "Unauthenticated requests can read files outside the web root, including session data.",
        "cve_id": "CVE-2018-13379",
        "cve_description": "FortiOS SSL VPN path traversal allows download of system files.",
        "cwe_id": "CWE-22",
        "cwe_description": "Improper limitation of a pathname to a restricted directory.",
    },
    {
        "vulnerability_name": "Pre-authentication RDP use-after-free",
        "vulnerability_description": "Two jump hosts expose RDP without network-level authentication.",
        "cve_id": "CVE-2019-0708",
        "cve_description": "Remote Desktop Services allows pre-auth remote code execution.",
        "cwe_id": "CWE-416",
        "cwe_description": "Use after free.",
    },
    {
        "vulnerability_name": "Spring data-binding to class loader properties",
        "vulnerability_description": "The internal API service binds request parameters onto class-loader-reachable properties.",
        "cve_id": "CVE-2022-22965",
        "cve_description": "Spring Framework data binding allows remote code execution on JDK 9+.",
        "cwe_id": "CWE-94",
        "cwe_description": "Improper control of generation of code.",
    },
    {
        "vulnerability_name": "Default credentials on the out-of-band controller",
        "vulnerability_description": "Two BMC interfaces still accept the vendor's shipped administrator password.",
        "cve_id": None,
        "cve_description": None,
        "cwe_id": "CWE-1392",
        "cwe_description": "Use of default credentials.",
    },
]

ANOMALIES = [
    ("ANOM-1", "Authentication burst outside working hours", "svc_backup", "Backup Service", "203.0.113.44", "10.14.2.10", "TCP"),
    ("ANOM-2", "Impossible travel between logins", "j.okafor", "Jide Okafor", "198.51.100.23", "10.14.2.37", "TCP"),
    ("ANOM-3", "Volumetric DNS TXT queries", "n/a", None, "10.14.9.11", "192.0.2.53", "UDP"),
    ("ANOM-4", "Repeated denied egress on a high port", "m.haddad", "Mira Haddad", "10.14.5.72", "203.0.113.90", "TCP"),
    ("ANOM-5", "Horizontal SMB session spray", "a.silva", "Ana Silva", "10.14.5.72", "10.14.7.0", "TCP"),
    ("ANOM-6", "First-seen process on nineteen hosts", "SYSTEM", "Local System", "10.14.7.14", "10.14.7.14", "N/A"),
    ("ANOM-7", "Periodic beacon at fixed interval", "svc_report", "Reporting Service", "10.14.2.37", "203.0.113.44", "TCP"),
    ("ANOM-8", "Privileged group membership change", "d.novak", "Dan Novak", "10.14.1.5", "10.14.1.20", "TCP"),
    ("ANOM-9", "Shadow copy deletion", "SYSTEM", "Local System", "10.14.7.31", "10.14.7.31", "N/A"),
    ("ANOM-10", "Spike in denied proxy categories", "k.tan", "Kai Tan", "10.14.3.18", "198.51.100.77", "TCP"),
]

TIMELINE_EVENTS = [
    ("Initial authentication failure burst", "vpn-gw-01", "00:12"),
    ("First successful login from new geography", "vpn-gw-01", "00:41"),
    ("Internal port sweep begins", "wks-4471", "01:03"),
    ("SMB session established to file server", "fs-02", "01:27"),
    ("Encoded interpreter launched", "wks-4471", "01:31"),
    ("Outbound beacon first observed", "wks-4471", "01:44"),
    ("Credential material accessed in memory", "wks-4471", "02:06"),
    ("Privileged group membership modified", "dc-01", "02:35"),
    ("Archive staged in temporary directory", "fs-02", "03:02"),
    ("Bulk outbound transfer", "fs-02", "03:19"),
    ("Shadow copies removed", "fs-02", "03:48"),
    ("Containment applied to affected hosts", "soc-console", "04:15"),
]

CLASSIFICATIONS = ["Internal", "Confidential", "Restricted"]

# Enrichment the n8n orchestrator would have produced: AbuseIPDB reputation for
# the IPs its indicator-extraction pass found, plus its own IOC classification.
INDICATORS = [
    ("203.0.113.44", "ip", "External Infrastructure", "abuseipdb", 94, "CRITICAL", "RU", "Data Center/Web Hosting"),
    ("198.51.100.23", "ip", "External Infrastructure", "abuseipdb", 71, "HIGH", "NL", "Data Center/Web Hosting"),
    ("192.0.2.17", "ip", "External Infrastructure", "abuseipdb", 38, "MEDIUM", "US", "Commercial"),
    ("10.14.2.37", "ip", "Internal Infrastructure", "abuseipdb", 0, "LOW", "-", "Reserved"),
    ("203.0.113.90", "ip", "External Infrastructure", "abuseipdb", 82, "HIGH", "CN", "Data Center/Web Hosting"),
    ("cdn-metrics-eu.example", "domain", "Network Indicator", "n8n", None, "MEDIUM", None, None),
    ("update-svc.example", "domain", "Network Indicator", "n8n", None, "HIGH", None, None),
    ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "hash", "Malware Artifact", "virustotal", 46, "CRITICAL", None, None),
    ("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08", "hash", "Malware Artifact", "virustotal", 3, "LOW", None, None),
]

ALERT_TEMPLATES = [
    ("critical", "FIM & Audit Engine", "File integrity mismatch on the source log for {report}. The file no longer matches the hash recorded when the report was generated."),
    ("high", "FIM & Audit Engine", "VirusTotal flagged the source artifact for {report} as malicious across 46 engines."),
    ("medium", "AI Security Report Orchestrator", "Threat intelligence raised the risk score for {report} above the alerting threshold."),
    ("low", "AI Security Report Orchestrator", "Report {report} completed with one section missing; enrichment ran on partial data."),
]

REPORT_TITLES = [
    "Perimeter log review",
    "VPN authentication audit",
    "DNS egress analysis",
    "Endpoint telemetry sweep",
    "Web proxy review",
    "Weekly threat summary",
    "Lateral movement investigation",
    "Ransomware precursor check",
    "Credential exposure review",
    "Outbound channel analysis",
    "Privileged access audit",
    "Perimeter appliance assessment",
    "East-west traffic review",
    "Incident retrospective",
]


def seed_demo(db, owners: list[Users], days: int = WINDOW_DAYS) -> dict[str, int]:
    """Write the demo history for each owner. Returns per-table row counts."""
    rng = random.Random(SEED)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    counts = {"documents": 0, "reports": 0, "findings": 0}

    for owner_index, owner in enumerate(owners):
        # Running --demo twice must not double the history. Re-seeding is
        # `--reset --demo`, which is explicit about deleting first.
        if db.scalar(select(func.count(Report.report_id)).where(Report.user_id == owner.user_id)):
            print(f"demo data already present for {owner.email}, skipping")
            continue

        documents = _seed_documents(db, owner, rng)
        counts["documents"] += len(documents)

        for index in range(REPORTS_PER_OWNER):
            report = _seed_report(
                db,
                owner=owner,
                document=rng.choice(documents),
                title=REPORT_TITLES[(index + owner_index * 3) % len(REPORT_TITLES)],
                generated_at=_stagger(today, days, index, owner_index, rng),
                rng=rng,
            )
            counts["reports"] += 1
            counts["findings"] += report

    return counts


def _stagger(
    today: datetime, days: int, index: int, owner_index: int, rng: random.Random
) -> datetime:
    """Spread reports back across the window, clustered on weekdays.

    Evenly spaced timestamps produce a flat line, which is a chart that proves
    nothing. Weekday clustering and a jittered hour give the series the shape
    real analyst activity has.
    """
    span = days - 2
    offset = int(span * (index + owner_index * 0.4) / max(REPORTS_PER_OWNER, 1))
    day = today - timedelta(days=span - offset)
    if day.weekday() >= 5:
        day -= timedelta(days=day.weekday() - 4)
    return day + timedelta(hours=rng.randint(8, 18), minutes=rng.randrange(0, 60, 5))


def _seed_documents(db, owner: Users, rng: random.Random) -> list[Document]:
    """One log file per demo document, written to the upload directory.

    Real files rather than dangling paths: the Documents page shows a size that
    matches something on disk, and Phase 5's integrity hashing has a file to
    hash.
    """
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    documents: list[Document] = []

    for name, header in DEMO_DOCUMENTS:
        path = settings.upload_dir / f"{owner.user_id.hex[:8]}_{name}"
        _write_log(path, header)
        stat = path.stat()
        created = datetime.now(timezone.utc) - timedelta(days=rng.randint(30, 60))

        document = Document(
            document_name=name,
            document_size=float(stat.st_size),
            document_extension=Path(name).suffix,
            document_path=str(path),
            created_at=created,
            modified_at=created + timedelta(hours=rng.randint(1, 48)),
            uploaded_at=created,
            user_id=owner.user_id,
        )
        db.add(document)
        documents.append(document)

    db.flush()
    return documents


def _write_log(path: Path, header: str) -> None:
    lines = [header, *_LOG_ROWS]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_report(
    db,
    *,
    owner: Users,
    document: Document,
    title: str,
    generated_at: datetime,
    rng: random.Random,
) -> int:
    """One report and its five sections. Returns the number of finding rows."""
    # Roughly one report in seven did not come back clean. A dashboard where
    # every report succeeded cannot demonstrate the state it exists to surface.
    roll = rng.random()
    status = "complete" if roll < 0.79 else "partial" if roll < 0.93 else "failed"
    error_detail = None
    if status == "partial":
        error_detail = "vulnerabilities: model output failed validation twice"
    elif status == "failed":
        error_detail = "provider unreachable: connection reset while generating sections"

    # Most reports have been audited and match; a few have never been checked;
    # one in twelve is TAMPERED, which is what makes the badge worth having.
    integrity_roll = rng.random()
    integrity_state = (
        "SEALED" if integrity_roll < 0.72 else "UNKNOWN" if integrity_roll < 0.92 else "TAMPERED"
    )

    report = Report(
        report_name=f"{title} — {document.document_name}",
        document_id=document.document_id,
        user_id=owner.user_id,
        generated_at=generated_at,
        classification=rng.choice(CLASSIFICATIONS),
        status=status,
        error_detail=error_detail,
        file_hash=hash_document(document.document_path),
        integrity_state=integrity_state,
        integrity_checked_at=(
            generated_at + timedelta(hours=rng.randint(1, 36))
            if integrity_state != "UNKNOWN"
            else None
        ),
    )
    db.add(report)
    db.flush()

    if integrity_state == "TAMPERED":
        severity, source, template = ALERT_TEMPLATES[0]
        _add_alert(db, report, owner, severity, source, template, generated_at, rng, resolved=False)
    elif rng.random() < 0.18:
        severity, source, template = rng.choice(ALERT_TEMPLATES[1:])
        _add_alert(
            db, report, owner, severity, source, template, generated_at, rng,
            resolved=rng.random() < 0.55,
        )

    if status == "failed":
        # A failed report has no sections. Giving it findings anyway would make
        # the "needs attention" tile disagree with what the report page shows.
        return 0

    findings = 0
    for attack in rng.sample(ATTACKS, rng.randint(2, 5)):
        db.add(AttackType(report_id=report.report_id, **attack))
        findings += 1

    for risk in rng.sample(GENERAL_RISKS, rng.randint(1, 3)):
        db.add(RiskAssessment(report_id=report.report_id, **risk))
        findings += 1

    if status != "partial":
        for vulnerability in rng.sample(VULNERABILITIES, rng.randint(1, 4)):
            db.add(Vulnerability(report_id=report.report_id, **vulnerability))
            findings += 1

    for anomaly in rng.sample(ANOMALIES, rng.randint(2, 6)):
        anomaly_id, name, user_id, user_name, source, destination, protocol = anomaly
        first = generated_at - timedelta(hours=rng.randint(2, 20))
        db.add(
            Anomaly(
                report_id=report.report_id,
                anomaly_id=anomaly_id,
                anomaly_name=name,
                user_id=user_id,
                user_name=user_name,
                source_ip=source,
                destination_ip=destination,
                protocol=protocol,
                counted=rng.choice([3, 8, 17, 42, 96, 214, 630, 1480]),
                first_occurrence=first.isoformat(timespec="seconds"),
                last_occurrence=generated_at.isoformat(timespec="seconds"),
            )
        )
        findings += 1

    start = rng.randint(0, len(TIMELINE_EVENTS) - 5)
    for event_name, entity, time_stamp in TIMELINE_EVENTS[start : start + rng.randint(4, 6)]:
        db.add(
            Timeline(
                report_id=report.report_id,
                event_name=event_name,
                entity=entity,
                time_stamp=f"{generated_at.date().isoformat()}T{time_stamp}:00Z",
                duration=f"{rng.randint(1, 45)}m",
            )
        )
        findings += 1

    # Not every report is enriched — the orchestrator runs threat intel, the
    # in-app generator does not, and the Report Detail page has to handle both.
    if rng.random() < 0.65:
        for row in rng.sample(INDICATORS, rng.randint(2, 5)):
            indicator, kind, category, source, score, level, country, usage = row
            db.add(
                ThreatIntel(
                    report_id=report.report_id,
                    indicator=indicator,
                    indicator_type=kind,
                    category=category,
                    source=source,
                    reputation_score=score,
                    risk_level=level,
                    country=country,
                    usage_type=usage,
                    raw={"abuseConfidenceScore": score} if score is not None else None,
                )
            )
            findings += 1

    return findings


def _add_alert(db, report, owner, severity, source, template, generated_at, rng, *, resolved):
    raised = generated_at + timedelta(hours=rng.randint(1, 30))
    db.add(
        SecurityAlert(
            severity=severity,
            source=source,
            message=template.format(report=report.report_name),
            status="resolved" if resolved else "open",
            report_id=report.report_id,
            document_id=report.document_id,
            user_id=owner.user_id,
            created_at=raised,
            resolved_at=raised + timedelta(hours=rng.randint(1, 20)) if resolved else None,
        )
    )
