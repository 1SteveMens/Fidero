"""INS rules enforced a second time in PostgreSQL (02 6.12, RUL-25). Function bodies avoid the upper-case
word ON (core.dbsql reads it as a trigger's table)."""
from core.dbsql import append_only

SQL = [
    # ins.insurer_payee_kind(): a policy's premium account is an insurer's payee record (RUL-25).
    """
    CREATE OR REPLACE FUNCTION ins_policy_insurer_payee() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM esc_payee p WHERE p.id = NEW.insurer_payee_id AND p.kind = 'insurer') THEN
        RAISE EXCEPTION 'A premium is paid only to an insurer''s payee record (RUL-25)'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_ins_policy_insurer_payee ON ins_policy;",
    """CREATE TRIGGER trg_ins_policy_insurer_payee BEFORE INSERT OR UPDATE ON ins_policy
       FOR EACH ROW EXECUTE FUNCTION ins_policy_insurer_payee();""",
    # ins_insurer.payee is kind insurer.
    """
    CREATE OR REPLACE FUNCTION ins_insurer_payee_kind() RETURNS trigger AS $$
    BEGIN
      IF NEW.payee_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM esc_payee p WHERE p.id = NEW.payee_id
                                                   AND p.kind = 'insurer') THEN
        RAISE EXCEPTION 'An insurer''s premium account is a payee of kind insurer (RUL-25)'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_ins_insurer_payee_kind ON ins_insurer;",
    """CREATE TRIGGER trg_ins_insurer_payee_kind BEFORE INSERT OR UPDATE ON ins_insurer
       FOR EACH ROW EXECUTE FUNCTION ins_insurer_payee_kind();""",
    # A premium instruction pays this premium to the policy's insurer payee (RUL-25).
    """
    CREATE OR REPLACE FUNCTION ins_premium_to_insurer() RETURNS trigger AS $$
    BEGIN
      IF NEW.release_instruction_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM esc_release_instruction r, ins_policy pol
           WHERE pol.id = NEW.policy_id AND r.id = NEW.release_instruction_id
             AND r.payee_id = pol.insurer_payee_id AND r.subject_type = 'premium' AND r.subject_id = NEW.id) THEN
        RAISE EXCEPTION 'A premium instruction pays only the insurer''s payee for this premium (RUL-25)'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_ins_premium_to_insurer ON ins_premium;",
    """CREATE TRIGGER trg_ins_premium_to_insurer BEFORE INSERT OR UPDATE ON ins_premium
       FOR EACH ROW EXECUTE FUNCTION ins_premium_to_insurer();""",
    *append_only("ins_claim_update"),
]
