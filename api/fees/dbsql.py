"""FEE rules enforced a second time in PostgreSQL (02 6.12, ADR-02).

Function bodies avoid the upper-case word ON: core.dbsql skips a statement whose ON clause names a
table that does not exist yet."""

SQL = [
    # fee.institution_verified_means_payee_verified(): 'verified' needs a verified, matched payee (RUL-22).
    """
    CREATE OR REPLACE FUNCTION fee_institution_verified_payee() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'verified' AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'verified') THEN
        IF NOT EXISTS (SELECT 1 FROM esc_payee p WHERE p.id = NEW.payee_id AND p.verification_status = 'verified'
                        AND p.name_match = 'matched' AND p.kind = 'institution') THEN
          RAISE EXCEPTION 'An institution is verified only with a verified institution payee (RUL-22)'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_fee_institution_verified_payee ON fee_institution;",
    """CREATE TRIGGER trg_fee_institution_verified_payee BEFORE INSERT OR UPDATE ON fee_institution
       FOR EACH ROW EXECUTE FUNCTION fee_institution_verified_payee();""",
    # fee.family_member_belongs_to_client() and fee.invoice_institution_eligible() (FR-FEE-006).
    """
    CREATE OR REPLACE FUNCTION fee_invoice_rules() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM acc_family_member f WHERE f.id = NEW.family_member_id
                      AND f.client_id = NEW.client_id) THEN
        RAISE EXCEPTION 'The family member is not the client''s' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.check_status = 'checked' AND (TG_OP = 'INSERT' OR OLD.check_status IS DISTINCT FROM 'checked') THEN
        IF NOT EXISTS (SELECT 1 FROM fee_institution i WHERE i.id = NEW.institution_id
                        AND i.eligible_for_direct_payment) THEN
          RAISE EXCEPTION 'An invoice is checked only for an institution eligible for direct payment (FR-FEE-006)'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF NEW.status = 'client_approved' AND TG_OP = 'UPDATE' AND OLD.status = 'checked' THEN
        IF NOT EXISTS (SELECT 1 FROM fee_institution i WHERE i.id = NEW.institution_id
                        AND i.eligible_for_direct_payment) THEN
          RAISE EXCEPTION 'An invoice is approved only for an institution eligible for direct payment (FR-FEE-006)'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_fee_invoice_rules ON fee_invoice;",
    """CREATE TRIGGER trg_fee_invoice_rules BEFORE INSERT OR UPDATE ON fee_invoice
       FOR EACH ROW EXECUTE FUNCTION fee_invoice_rules();""",
    # fee.payment_payee_is_institution(): the instruction pays this invoice to this institution's payee (RUL-22).
    """
    CREATE OR REPLACE FUNCTION fee_payment_payee_is_institution() RETURNS trigger AS $$
    BEGIN
      IF NEW.release_instruction_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM esc_release_instruction r, fee_invoice v, fee_institution i
           WHERE v.id = NEW.invoice_id AND i.id = v.institution_id
             AND r.id = NEW.release_instruction_id AND r.payee_id = i.payee_id
             AND r.subject_type = 'fee_invoice' AND r.subject_id = v.id) THEN
        RAISE EXCEPTION 'A fee payment instruction pays only the institution''s payee for this invoice (RUL-22)'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_fee_payment_payee ON fee_payment;",
    """CREATE TRIGGER trg_fee_payment_payee BEFORE INSERT OR UPDATE ON fee_payment
       FOR EACH ROW EXECUTE FUNCTION fee_payment_payee_is_institution();""",
]
