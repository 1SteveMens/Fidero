"""Evidence rules enforced again in PostgreSQL (ADR-02, ADR-04, FR-EVD-002, RUL-30).

- evd_evidence: no DELETE; identity, hash, provenance, capture and server time never change;
  retain_until may only grow; deleted_at is set once, and only after retain_until.
- evd_link and every log table are append-only.
- evd.official_search_link(): an 'official_search_result' link only on a search_request, linked and
  received by case managers or reviewers who hold none of the excluded roles (RUL-30, FR-CASE-016).
"""
from core.dbsql import append_only

_IMMUTABLE = ["sha256", "storage_key", "size_bytes", "content_type", "original_name", "source", "provenance",
              "device_id", "uploaded_by_id", "captured_at", "received_at", "latitude", "longitude",
              "position_accuracy_m", "country_id", "object_version", "owner_type", "owner_id", "phash"]
_changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in _IMMUTABLE)

SQL = append_only("evd_link") + append_only("evd_scan_result") + append_only("evd_access_log") \
    + append_only("evd_issued_document") + append_only("evd_fingerprint_check") \
    + append_only("evd_retention_deletion") + append_only("evd_preview") + [
    f"""CREATE OR REPLACE FUNCTION evd_immutable() RETURNS trigger AS $$
    BEGIN
      IF {_changed} THEN
        RAISE EXCEPTION 'Evidence is tamper-evident and cannot change' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF OLD.retain_until IS NOT NULL AND (NEW.retain_until IS NULL OR NEW.retain_until < OLD.retain_until) THEN
        RAISE EXCEPTION 'Retention can be extended, never shortened' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN
        RAISE EXCEPTION 'A retention deletion cannot be undone or changed' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL
         AND (OLD.retain_until IS NULL OR OLD.retain_until >= current_date) THEN
        RAISE EXCEPTION 'Evidence is locked until its retention date' USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_evd_immutable ON evd_evidence;",
    "CREATE TRIGGER trg_evd_immutable BEFORE UPDATE ON evd_evidence FOR EACH ROW EXECUTE FUNCTION evd_immutable();",
    "DROP TRIGGER IF EXISTS trg_evd_no_delete ON evd_evidence;",
    """CREATE TRIGGER trg_evd_no_delete BEFORE DELETE ON evd_evidence FOR EACH ROW
       EXECUTE FUNCTION core_append_only();""",
    """CREATE OR REPLACE FUNCTION evd_is_search_staff(p uuid, cid uuid) RETURNS boolean AS $$
      SELECT p IS NOT NULL
        AND EXISTS (SELECT 1 FROM acc_role_grant g WHERE g.person_id = p AND g.revoked_at IS NULL
                     AND g.role IN ('CM', 'RV') AND (g.country_id IS NULL OR g.country_id = cid))
        AND NOT EXISTS (SELECT 1 FROM acc_role_grant g WHERE g.person_id = p AND g.revoked_at IS NULL
                     AND g.role IN ('RN', 'SE', 'DV', 'CL', 'CE') AND (g.country_id IS NULL OR g.country_id = cid));
    $$ LANGUAGE sql STABLE;""",
    """CREATE OR REPLACE FUNCTION evd_official_search_link() RETURNS trigger AS $$
    DECLARE up uuid; cid uuid;
    BEGIN
      IF NEW.role = 'official_search_result' THEN
        IF NEW.subject_type <> 'search_request' THEN
          RAISE EXCEPTION 'RUL-30: an official search result links only to a search request'
            USING ERRCODE = 'check_violation';
        END IF;
        SELECT e.uploaded_by_id, e.country_id INTO up, cid FROM evd_evidence e WHERE e.id = NEW.evidence_id;
        IF NOT evd_is_search_staff(NEW.linked_by_id, cid) OR NOT evd_is_search_staff(up, cid) THEN
          RAISE EXCEPTION 'RUL-30: only case managers or reviewers handle official search results'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_evd_official_search_link ON evd_link;",
    """CREATE TRIGGER trg_evd_official_search_link BEFORE INSERT ON evd_link FOR EACH ROW
       EXECUTE FUNCTION evd_official_search_link();""",
]
