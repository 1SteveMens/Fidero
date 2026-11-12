from core.dbsql import append_only

SQL = append_only("evd_link") + [
    # Evidence rows never change their hash or storage key.
    """CREATE OR REPLACE FUNCTION evd_immutable() RETURNS trigger AS $$
    BEGIN
      IF NEW.sha256 <> OLD.sha256 OR NEW.storage_key <> OLD.storage_key OR NEW.size_bytes <> OLD.size_bytes THEN
        RAISE EXCEPTION 'Evidence is tamper-evident and cannot change' USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_evd_immutable ON evd_evidence;",
    "CREATE TRIGGER trg_evd_immutable BEFORE UPDATE ON evd_evidence FOR EACH ROW EXECUTE FUNCTION evd_immutable();",
    "DROP TRIGGER IF EXISTS trg_evd_no_delete ON evd_evidence;",
    """CREATE TRIGGER trg_evd_no_delete BEFORE DELETE ON evd_evidence FOR EACH ROW
       EXECUTE FUNCTION core_append_only();""",
]
