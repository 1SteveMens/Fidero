"""PRJ rules enforced again in PostgreSQL (ADR-02).

- prj.agreement_statement(): every project agreement carries the no-advice statement (the working text, or the
  country's published locked text `no_advice_statement`), and its text never changes once written (FR-PRJ-005,
  TC-PRJ-005-02).
- prj.invoice_payee(): a payment for a project invoice pays the invoice's own supplier, which is checked, and
  never the person running the project (RUL-21).
"""
from .models import NO_ADVICE_STATEMENT

_STMT = NO_ADVICE_STATEMENT.replace("'", "''")

SQL = [
    f"""CREATE OR REPLACE FUNCTION prj_agreement_statement() RETURNS trigger AS $$
    BEGIN
      IF position('{_STMT}' in NEW.text) = 0 AND NOT EXISTS (
          SELECT 1 FROM adm_locked_text_version l
           WHERE l.kind = 'no_advice_statement' AND l.country_id = NEW.country_id
             AND l.status IN ('published', 'superseded') AND position(l.text in NEW.text) > 0) THEN
        RAISE EXCEPTION 'FR-PRJ-005: the agreement must carry the no-advice statement'
          USING ERRCODE = 'check_violation';
      END IF;
      IF TG_OP = 'UPDATE' AND (NEW.text IS DISTINCT FROM OLD.text OR NEW.text_sha256 IS DISTINCT FROM OLD.text_sha256)
      THEN
        RAISE EXCEPTION 'FR-PRJ-005: an agreement text never changes; write a new version'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_prj_agreement_statement ON prj_agreement;",
    """CREATE TRIGGER trg_prj_agreement_statement BEFORE INSERT OR UPDATE ON prj_agreement
       FOR EACH ROW EXECUTE FUNCTION prj_agreement_statement();""",
    """CREATE OR REPLACE FUNCTION prj_invoice_payee() RETURNS trigger AS $$
    DECLARE inv prj_invoice; sup prj_supplier;
    BEGIN
      IF NEW.subject_type <> 'project_invoice' OR NEW.status IN ('withdrawn', 'rejected') THEN
        RETURN NEW;
      END IF;
      SELECT * INTO inv FROM prj_invoice WHERE id = NEW.subject_id;
      SELECT * INTO sup FROM prj_supplier WHERE id = inv.supplier_id;
      IF inv.id IS NULL OR sup.payee_id IS DISTINCT FROM NEW.payee_id OR sup.status <> 'passed' THEN
        RAISE EXCEPTION 'RUL-21: a project fund payment goes only to the invoice''s own checked supplier'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_prj_invoice_payee ON bld_payment;",
    """CREATE TRIGGER trg_prj_invoice_payee BEFORE INSERT OR UPDATE ON bld_payment
       FOR EACH ROW EXECUTE FUNCTION prj_invoice_payee();""",
]
