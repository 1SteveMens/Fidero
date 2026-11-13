"""DPR rules enforced again in PostgreSQL (ADR-02). Function bodies must not
contain the text " ON " in capitals (core.dbsql.install reads it as a table)."""
from core.dbsql import append_only

SQL = append_only("dpr_privacy_acceptance") + [
    # FR-DPR-005: a bulk export file exists only after its approval closed as approved.
    """CREATE OR REPLACE FUNCTION dpr_bulk_export_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'produced' AND NOT EXISTS (
          SELECT 1 FROM core_approval_request r
           WHERE r.id = NEW.approval_request_id AND r.status = 'approved' AND r.subject_type = 'bulk_export') THEN
        RAISE EXCEPTION 'A bulk export needs two-person approval' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_dpr_bulk_export_rules ON dpr_bulk_export;",
    """CREATE TRIGGER trg_dpr_bulk_export_rules BEFORE INSERT OR UPDATE ON dpr_bulk_export
       FOR EACH ROW EXECUTE FUNCTION dpr_bulk_export_rules();""",
    # FR-DPR-004: a legal hold is lifted only after its two-person approval, and never deleted.
    """CREATE OR REPLACE FUNCTION dpr_legal_hold_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'lifted' AND NOT EXISTS (
          SELECT 1 FROM core_approval_request r
           WHERE r.id = NEW.approval_request_id AND r.status = 'approved' AND r.subject_type = 'legal_hold') THEN
        RAISE EXCEPTION 'Lifting a legal hold needs two-person approval' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_dpr_legal_hold_rules ON dpr_legal_hold;",
    """CREATE TRIGGER trg_dpr_legal_hold_rules BEFORE INSERT OR UPDATE ON dpr_legal_hold
       FOR EACH ROW EXECUTE FUNCTION dpr_legal_hold_rules();""",
    "DROP TRIGGER IF EXISTS trg_dpr_legal_hold_no_delete ON dpr_legal_hold;",
    """CREATE TRIGGER trg_dpr_legal_hold_no_delete BEFORE DELETE ON dpr_legal_hold
       FOR EACH ROW EXECUTE FUNCTION core_append_only();""",
]
