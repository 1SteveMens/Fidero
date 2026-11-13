"""FR-NTF-005: the delivery log is append-only. ADR-20: a confirmation code's
hash never changes and a confirmed confirmation is never reopened."""
from core.dbsql import append_only

SQL = append_only("ntf_delivery_event") + [
    """
    CREATE OR REPLACE FUNCTION ntf_confirmation_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.code_hash IS DISTINCT FROM OLD.code_hash OR NEW.link_token_hash IS DISTINCT FROM OLD.link_token_hash
         OR NEW.subject_id IS DISTINCT FROM OLD.subject_id OR NEW.subject_type IS DISTINCT FROM OLD.subject_type THEN
        RAISE EXCEPTION 'A confirmation code cannot be changed' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.attempts < OLD.attempts THEN
        RAISE EXCEPTION 'Wrong tries cannot be undone' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.status = 'confirmed' AND NEW.confirmed_via = 'staff_call'
         AND (NEW.call_checked_by_id IS NULL OR NEW.call_checked_by_id = NEW.call_recorded_by_id) THEN
        RAISE EXCEPTION 'A staff call needs a second staff member' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_ntf_confirmation_rules ON ntf_confirmation_code;",
    """CREATE TRIGGER trg_ntf_confirmation_rules BEFORE UPDATE ON ntf_confirmation_code
       FOR EACH ROW EXECUTE FUNCTION ntf_confirmation_rules();""",
]
