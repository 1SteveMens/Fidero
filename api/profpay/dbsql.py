"""PRO rules enforced a second time in PostgreSQL (02 6.14, ADR-02, ADR-23).

- pro_scope: written only by migration; no key or description names a result (RUL-26).
- pro_rate_card: immutable once approved; approved versions of one key never overlap.
- pro_payable: the rate card is the approved card for the role, unit and scope valid when the work was
  assigned, and the unit rate equals its rate (RUL-26).
- pro_agreement and pro_payment_line: the destination is a verified account in the professional's (or the
  signing firm's) own name with a matching account name (FR-PRO-006, RUL-22).
- pro_payment_run: debits only an operating account of the same country (RUL-27); the approver holds payment
  rights and is not the preparer (FR-PRO-005).
- pro_payment_line: a confirmed line never changes; pro_document and pro_runner_month are append-only.
"""
from core.dbsql import append_only

RESULT_REGEX = "(verdict|outcome|pass|fail|green|amber|red|risk|finding|defect|result)"

SQL = [
    # ------------------------------------------------------------------ pro_scope (RUL-26)
    f"""
    CREATE OR REPLACE FUNCTION pro_scope_guard() RETURNS trigger AS $$
    BEGIN
      IF coalesce(current_setting('tenmina.pro_scope_migration', true), '') <> 'on' THEN
        RAISE EXCEPTION 'pro_scope is seeded by migration only (RUL-26)' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF TG_OP <> 'DELETE' AND (lower(NEW.key) ~ '{RESULT_REGEX}' OR lower(NEW.description) ~ '{RESULT_REGEX}') THEN
        RAISE EXCEPTION 'A scope key may not name a result of the work (RUL-26)' USING ERRCODE = 'check_violation';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_pro_scope_guard ON pro_scope;",
    """CREATE TRIGGER trg_pro_scope_guard BEFORE INSERT OR UPDATE OR DELETE ON pro_scope
       FOR EACH ROW EXECUTE FUNCTION pro_scope_guard();""",

    # ------------------------------------------------------------------ pro_rate_card
    """
    CREATE OR REPLACE FUNCTION pro_rate_card_immutable() RETURNS trigger AS $$
    BEGIN
      IF OLD.state <> 'draft' AND (NEW.rate IS DISTINCT FROM OLD.rate OR NEW.unit IS DISTINCT FROM OLD.unit
          OR NEW.scope_key IS DISTINCT FROM OLD.scope_key OR NEW.role IS DISTINCT FROM OLD.role
          OR NEW.valid_from IS DISTINCT FROM OLD.valid_from OR NEW.currency IS DISTINCT FROM OLD.currency
          OR NEW.agreement_id IS DISTINCT FROM OLD.agreement_id OR NEW.country_id IS DISTINCT FROM OLD.country_id
          OR NEW.version IS DISTINCT FROM OLD.version) THEN
        RAISE EXCEPTION 'An approved rate card never changes; a change is a new version (FR-PRO-001)'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.state = 'approved' AND EXISTS (
          SELECT 1 FROM pro_rate_card o
           WHERE o.id <> NEW.id AND o.state = 'approved' AND o.country_id = NEW.country_id AND o.role = NEW.role
             AND o.agreement_id IS NOT DISTINCT FROM NEW.agreement_id AND o.unit = NEW.unit
             AND o.scope_key = NEW.scope_key
             AND daterange(o.valid_from, o.valid_to, '[]') && daterange(NEW.valid_from, NEW.valid_to, '[]')) THEN
        RAISE EXCEPTION 'Approved versions of one rate overlap' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_pro_rate_card_immutable ON pro_rate_card;",
    """CREATE TRIGGER trg_pro_rate_card_immutable BEFORE UPDATE ON pro_rate_card
       FOR EACH ROW EXECUTE FUNCTION pro_rate_card_immutable();""",

    # ------------------------------------------------------------------ pro_payable (RUL-26)
    """
    CREATE OR REPLACE FUNCTION pro_payable_rate() RETURNS trigger AS $$
    DECLARE c record; a record;
    BEGIN
      SELECT * INTO c FROM pro_rate_card WHERE id = NEW.rate_card_id;
      SELECT * INTO a FROM pro_agreement WHERE id = NEW.agreement_id;
      IF c.state <> 'approved' OR c.role <> a.role OR c.country_id <> NEW.country_id
         OR (c.agreement_id IS NOT NULL AND c.agreement_id <> NEW.agreement_id)
         OR c.valid_from > (NEW.assigned_at AT TIME ZONE 'UTC')::date
         OR (c.valid_to IS NOT NULL AND c.valid_to < (NEW.assigned_at AT TIME ZONE 'UTC')::date)
         OR c.rate <> NEW.unit_rate OR c.currency <> NEW.currency THEN
        RAISE EXCEPTION 'A payable takes the approved rate in force when the work was assigned (RUL-26)'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_pro_payable_rate ON pro_payable;",
    """CREATE TRIGGER trg_pro_payable_rate BEFORE INSERT OR UPDATE OF rate_card_id, unit_rate, assigned_at
       ON pro_payable FOR EACH ROW EXECUTE FUNCTION pro_payable_rate();""",

    # ------------------------------------------------------------------ destinations (FR-PRO-006)
    """
    CREATE OR REPLACE FUNCTION pro_destination_ok(p_payee uuid, p_account uuid, p_agreement uuid)
    RETURNS boolean AS $$
    DECLARE a record;
    BEGIN
      SELECT * INTO a FROM pro_agreement WHERE id = p_agreement;
      IF p_payee IS NOT NULL THEN
        RETURN EXISTS (SELECT 1 FROM esc_payee p WHERE p.id = p_payee
                         AND p.kind IN ('contracted_professional', 'professional')
                         AND p.verification_status = 'verified' AND p.name_match = 'matched'
                         AND ((a.contracting_party = 'person' AND (p.person_id = a.professional_id
                                OR (p.subject_type = 'person' AND p.subject_id = a.professional_id)))
                              OR (a.contracting_party = 'organisation' AND (p.organisation_id = a.organisation_id
                                OR (p.subject_type = 'organisation' AND p.subject_id = a.organisation_id)))));
      END IF;
      IF p_account IS NOT NULL THEN
        RETURN EXISTS (SELECT 1 FROM acc_bank_account b WHERE b.id = p_account
                         AND b.verification_status = 'verified' AND b.name_match = 'matched'
                         AND b.holder_id = a.professional_id AND a.contracting_party = 'person');
      END IF;
      RETURN false;
    END $$ LANGUAGE plpgsql STABLE;
    """,
    """
    CREATE OR REPLACE FUNCTION pro_agreement_payee() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'active' AND NOT pro_destination_ok(NEW.payee_id, NEW.bank_account_id, NEW.id) THEN
        RAISE EXCEPTION 'An active agreement pays only a verified account in the professional''s own name (FR-PRO-006)'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_pro_agreement_payee ON pro_agreement;",
    """CREATE CONSTRAINT TRIGGER trg_pro_agreement_payee AFTER INSERT OR UPDATE ON pro_agreement
       DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION pro_agreement_payee();""",
    """
    CREATE OR REPLACE FUNCTION pro_line_payee() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'INSERT' OR NEW.payee_id IS DISTINCT FROM OLD.payee_id
         OR NEW.bank_account_id IS DISTINCT FROM OLD.bank_account_id THEN
        IF NOT pro_destination_ok(NEW.payee_id, NEW.bank_account_id, NEW.agreement_id) THEN
          RAISE EXCEPTION 'A payment line pays only the professional''s verified account (FR-PRO-006, RUL-27)'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF TG_OP = 'UPDATE' AND OLD.outcome = 'confirmed' AND (NEW.gross <> OLD.gross
          OR NEW.withholding <> OLD.withholding OR NEW.other_deductions <> OLD.other_deductions
          OR NEW.reimbursed_expenses <> OLD.reimbursed_expenses OR NEW.outcome <> OLD.outcome
          OR NEW.payee_id IS DISTINCT FROM OLD.payee_id OR NEW.bank_account_id IS DISTINCT FROM OLD.bank_account_id)
      THEN
        RAISE EXCEPTION 'A paid line never changes; a correction is a new line' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_pro_line_payee ON pro_payment_line;",
    """CREATE TRIGGER trg_pro_line_payee BEFORE INSERT OR UPDATE ON pro_payment_line
       FOR EACH ROW EXECUTE FUNCTION pro_line_payee();""",

    # ------------------------------------------------------------------ pro_payment_run (RUL-27, FR-PRO-005)
    """
    CREATE OR REPLACE FUNCTION pro_run_rules() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM adm_partner p WHERE p.id = NEW.operating_account_id
                       AND p.kind IN ('operating_bank', 'operating_mobile_money')
                       AND p.country_id = NEW.country_id) THEN
        RAISE EXCEPTION 'A payment run debits only Tenmina''s operating account in its country (RUL-27)'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.approved_by_id IS NOT NULL AND (TG_OP = 'INSERT' OR OLD.approved_by_id IS DISTINCT FROM NEW.approved_by_id)
      THEN
        IF NOT EXISTS (SELECT 1 FROM acc_role_grant g WHERE g.person_id = NEW.approved_by_id AND g.role = 'PY'
                         AND g.revoked_at IS NULL AND (g.country_id IS NULL OR g.country_id = NEW.country_id)) THEN
          RAISE EXCEPTION 'The approver must hold payment rights (FR-PRO-005)' USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM core_approval a WHERE a.request_id = NEW.approval_request_id
                         AND a.approver_id = NEW.approved_by_id AND a.decision = 'approve') THEN
          RAISE EXCEPTION 'The approver must have approved the run' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_pro_run_rules ON pro_payment_run;",
    """CREATE TRIGGER trg_pro_run_rules BEFORE INSERT OR UPDATE ON pro_payment_run
       FOR EACH ROW EXECUTE FUNCTION pro_run_rules();""",
    *append_only("pro_document"),
    *append_only("pro_runner_month"),
]
