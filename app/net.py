"""Certificate trust setup.

Some Windows machines run antivirus software that terminates TLS and re-signs
every HTTPS response with its own certificate authority. Python does not trust
that authority by default, so every outbound request fails certificate
verification even though the connection is fine.

This module builds a combined trust bundle: the standard certifi roots plus any
locally installed interception authority it can find. It never disables
verification, which would leave the connection genuinely unverified.

Import and call `configure_trust()` once at process start, before any HTTP
client is created.
"""

from __future__ import annotations

import os
from pathlib import Path

import certifi

# Known locations where TLS-intercepting security software parks its root
# certificate. NODE_EXTRA_CA_CERTS is checked first because such software
# usually sets it for Node, and it is the most reliable pointer.
_CANDIDATE_ENV_VARS = ("NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")
_CANDIDATE_PATHS = (
    r"C:\ProgramData\Norton\Antivirus\wscert.pem",
    r"C:\ProgramData\Norton\wscert.pem",
    r"C:\ProgramData\Kaspersky Lab\shared\certs\(fake)Kaspersky Anti-Virus personal root certificate.crt",
    r"C:\ProgramData\ESET\ESET Security\certs\root.pem",
)

BUNDLE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "ca-bundle.pem"


def _extra_certificate_files() -> list[Path]:
    found: list[Path] = []
    for var in _CANDIDATE_ENV_VARS:
        raw = os.environ.get(var)
        if not raw:
            continue
        path = Path(raw.replace("\\\\", "\\"))
        if path.is_file() and path != Path(certifi.where()):
            found.append(path)
    for raw in _CANDIDATE_PATHS:
        path = Path(raw)
        if path.is_file():
            found.append(path)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for path in found:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def build_bundle(force: bool = False) -> Path:
    """Write the combined trust bundle and return its path."""
    extras = _extra_certificate_files()
    if not extras:
        return Path(certifi.where())

    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if BUNDLE_PATH.exists() and not force:
        return BUNDLE_PATH

    parts = [Path(certifi.where()).read_text(encoding="utf-8")]
    for path in extras:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "BEGIN CERTIFICATE" in text:
            parts.append(f"\n# added from {path}\n{text.strip()}\n")
    BUNDLE_PATH.write_text("\n".join(parts), encoding="utf-8")
    return BUNDLE_PATH


def configure_trust() -> Path:
    """Point every common HTTP client at the combined bundle."""
    bundle = build_bundle()
    value = str(bundle)
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ[var] = value
    return bundle
