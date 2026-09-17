"""Pseudonyms, date shifting and the re-identification vault.

Design:
  * pseudonym = "PSN-" + first 12 hex of HMAC-SHA256(secret, namespace || ":" || identifier). Deterministic, so
    the same patient arriving from Orthanc twice (or from openEHR and Orthanc) lands on the same pseudonym
    without a database round-trip. Keyed, so nobody without the secret can walk the id space.
  * date shift = per-patient offset in [-max_days, +max_days] derived from the same HMAC. Every date/time of
    that patient moves by the same offset, so intervals (follow-up at 6 months) survive while absolute dates do
    not. This is the DICOM PS3.15 "Retain Longitudinal Temporal Information with Modified Dates" option.
  * UIDs are re-mapped with a hash too (uid_map), so Study/Series/SOP instance UIDs stay internally consistent
    across all instances of a study but cannot be joined back to the source PACS.
  * the vault is the only place the (identifier -> pseudonym, offset) pair is written down. It exists for the
    legitimate re-identification path (incidental findings) and lives on separately protected storage.
    Pseudonymization = reversible with the vault; anonymization = the vault is not kept.
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Optional

ROOT_UID = "1.2.826.0.1.3680043.10.1234"   # placeholder org root; replace with your registered root


class Pseudonymizer:
    def __init__(self, secret_hex: str, namespace: str, vault_path: Optional[str] = None, max_shift_days: int = 365):
        self._key = bytes.fromhex(secret_hex)
        self.namespace = namespace
        self.max_shift_days = max_shift_days
        self._lock = threading.Lock()
        self._vault = sqlite3.connect(vault_path, check_same_thread=False) if vault_path else None
        if self._vault is not None:
            self._vault.execute(
                "CREATE TABLE IF NOT EXISTS reident (namespace TEXT, identifier TEXT, pseudonym TEXT, "
                "shift_days INTEGER, created_at TEXT, PRIMARY KEY (namespace, identifier))")
            self._vault.commit()

    # ---- primitives ----
    def _mac(self, *parts: str) -> bytes:
        return hmac.new(self._key, ":".join(parts).encode("utf-8"), hashlib.sha256).digest()

    def pseudonym(self, identifier: str) -> str:
        psn = "PSN-" + self._mac("id", self.namespace, identifier).hex()[:12].upper()
        self._record(identifier, psn)
        return psn

    def shift_days(self, identifier: str) -> int:
        n = int.from_bytes(self._mac("shift", self.namespace, identifier)[:4], "big")
        return n % (2 * self.max_shift_days + 1) - self.max_shift_days

    def shift_date(self, identifier: str, d: date) -> date:
        return d + timedelta(days=self.shift_days(identifier))

    def shift_datetime(self, identifier: str, dt: datetime) -> datetime:
        return dt + timedelta(days=self.shift_days(identifier))

    def uid(self, original_uid: str) -> str:
        """Deterministic replacement UID under our root; <= 64 chars per DICOM."""
        digest = int.from_bytes(self._mac("uid", original_uid)[:16], "big")
        return f"{ROOT_UID}.{digest}"[:64].rstrip(".")

    # ---- vault ----
    def _record(self, identifier: str, psn: str) -> None:
        if self._vault is None:
            return
        with self._lock:
            self._vault.execute(
                "INSERT OR IGNORE INTO reident VALUES (?, ?, ?, ?, ?)",
                (self.namespace, identifier, psn, self.shift_days(identifier), datetime.utcnow().isoformat()))
            self._vault.commit()

    def reidentify(self, pseudonym: str) -> Optional[str]:
        """Authorized reverse lookup. Only works if a vault was kept (pseudonymization, not anonymization)."""
        if self._vault is None:
            return None
        row = self._vault.execute("SELECT identifier FROM reident WHERE namespace=? AND pseudonym=?",
                                  (self.namespace, pseudonym)).fetchone()
        return row[0] if row else None
