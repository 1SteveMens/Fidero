"""MOB rules enforced again in PostgreSQL (ADR-02).

- A signed manifest never changes what was signed, by whom or when it arrived.
- A device key stays bound to one person.
- Check-ins and submission items are append-only; a check-out needs a check-in first
  (trigger mob.checkout_after_checkin(), 02 section 6.6).
- A fraud flag keeps its kind and detail; only its review fields change.
"""
from core.dbsql import append_only


def _immutable(table, fn, cols, extra=""):
    changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in cols)
    return [
        f"""CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$
        BEGIN
          IF {changed} THEN
            RAISE EXCEPTION '% keeps what was signed and recorded', TG_TABLE_NAME
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          {extra}
          RETURN NEW;
        END $$ LANGUAGE plpgsql;""",
        f"DROP TRIGGER IF EXISTS trg_{fn} ON {table};",
        f"CREATE TRIGGER trg_{fn} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}();",
    ]


SQL = (
    append_only("mob_checkin") + append_only("mob_submission_item")
    + _immutable("mob_signed_manifest", "mob_manifest_immutable",
                 ["manifest", "canonical_sha256", "item_sha256", "signature", "signature_alg", "signature_valid",
                  "person_id", "device_id", "client_item_id", "captured_at_device", "received_at", "latitude",
                  "longitude", "media_sha256", "subject_type", "subject_id", "reserved_evidence_id"],
                 extra="""IF OLD.evidence_id IS NOT NULL AND NEW.evidence_id IS DISTINCT FROM OLD.evidence_id THEN
            RAISE EXCEPTION 'A stored item keeps its evidence' USING ERRCODE = 'insufficient_privilege';
          END IF;""")
    + _immutable("mob_device", "mob_device_immutable", ["person_id", "public_key", "key_fingerprint", "key_alg",
                                                        "platform", "registered_at"])
    + _immutable("mob_fraud_flag", "mob_flag_immutable", ["kind", "detail", "manifest_id", "checkin_id",
                                                          "created_at"],
                 extra="""IF OLD.evidence_id IS NOT NULL AND NEW.evidence_id IS DISTINCT FROM OLD.evidence_id THEN
            RAISE EXCEPTION 'A flag keeps its evidence' USING ERRCODE = 'insufficient_privilege';
          END IF;""")
    + _immutable("mob_submission", "mob_submission_immutable", ["client_submission_id", "person_id", "kind",
                                                                "subject_type", "subject_id", "outcome",
                                                                "checklist", "defects", "received_at"])
    + [
        """CREATE OR REPLACE FUNCTION mob_checkout_after_checkin() RETURNS trigger AS $$
        BEGIN
          IF NEW.kind = 'checkout' AND NOT EXISTS (
              SELECT 1 FROM mob_checkin c WHERE c.subject_type = NEW.subject_type AND c.subject_id = NEW.subject_id
                AND c.kind = 'checkin' AND c.device_time <= NEW.device_time) THEN
            RAISE EXCEPTION 'A check-out needs an earlier check-in for the same work' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;""",
        "DROP TRIGGER IF EXISTS trg_mob_checkout_after_checkin ON mob_checkin;",
        """CREATE TRIGGER trg_mob_checkout_after_checkin BEFORE INSERT ON mob_checkin FOR EACH ROW
           EXECUTE FUNCTION mob_checkout_after_checkin();""",
    ]
)
