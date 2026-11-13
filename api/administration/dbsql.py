"""Rules the database enforces a second time (ADR-02, ADR-11, 02 sections 6.8 and 6.9).

Function bodies avoid the upper-case word used by core.dbsql to find a
statement's table, so keep SQL keywords there in lower case where needed.
"""
from core.dbsql import append_only


def _trigger(name, table, when, func):
    return [
        f"DROP TRIGGER IF EXISTS {name} ON {table};",
        f"CREATE TRIGGER {name} {when} ON {table} FOR EACH ROW EXECUTE FUNCTION {func}();",
    ]


SQL = [
    # ADR-11: a published or retired configuration version never changes.
    """
    CREATE OR REPLACE FUNCTION adm_config_immutable() RETURNS trigger AS $$
    BEGIN
      IF OLD.state <> 'draft' AND (NEW.content IS DISTINCT FROM OLD.content
          OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256 OR NEW.version IS DISTINCT FROM OLD.version
          OR NEW.kind IS DISTINCT FROM OLD.kind OR NEW.country_id IS DISTINCT FROM OLD.country_id) THEN
        RAISE EXCEPTION 'A published configuration version cannot change' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    *_trigger("trg_adm_config_immutable", "adm_config_version", "BEFORE UPDATE", "adm_config_immutable"),
    # FR-ADM-004, RUL-04: locked text is immutable once out of draft; publishing needs the
    # approval and, for the scope statement, the lawyer's and insurer's recorded approvals.
    """
    CREATE OR REPLACE FUNCTION adm_locked_text_rules() RETURNS trigger AS $$
    BEGIN
      IF OLD.status NOT IN ('draft') AND (NEW.text IS DISTINCT FROM OLD.text
          OR NEW.text_sha256 IS DISTINCT FROM OLD.text_sha256) THEN
        RAISE EXCEPTION 'A locked text cannot change after it is sent for approval'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.status = 'published' AND OLD.status <> 'published' THEN
        IF NEW.approval_request_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM core_approval_request r WHERE r.id = NEW.approval_request_id AND r.status = 'approved') THEN
          RAISE EXCEPTION 'A locked text needs an approved two-person request' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.kind = 'scope_statement' AND (NEW.lawyer_approval_evidence_id IS NULL
            OR NEW.insurer_approval_evidence_id IS NULL) THEN
          RAISE EXCEPTION 'The scope statement needs the lawyer and insurer approvals'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    *_trigger("trg_adm_locked_text_rules", "adm_locked_text_version", "BEFORE UPDATE", "adm_locked_text_rules"),
    # FR-ADM-003: bank details change only with an approved change request.
    # ADR-23, RUL-27: an operating account never matches an escrow account (adm.operating_not_escrow).
    """
    CREATE OR REPLACE FUNCTION adm_partner_bank_rules() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'UPDATE' AND (NEW.account_number IS DISTINCT FROM OLD.account_number
          OR NEW.account_name IS DISTINCT FROM OLD.account_name OR NEW.bank_name IS DISTINCT FROM OLD.bank_name) THEN
        IF NEW.bank_change_request_id IS NULL OR NEW.bank_change_request_id IS NOT DISTINCT FROM OLD.bank_change_request_id
           OR NOT EXISTS (SELECT 1 FROM adm_change_request c, core_approval_request r
                           WHERE c.id = NEW.bank_change_request_id AND r.id = c.approval_request_id
                             AND r.status = 'approved') THEN
          RAISE EXCEPTION 'Bank details need a second administrator' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF TG_OP = 'INSERT' AND NEW.account_number <> '' THEN
        RAISE EXCEPTION 'Bank details need a second administrator' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.account_number_bidx <> '' AND EXISTS (
          SELECT 1 FROM adm_partner p WHERE p.account_number_bidx = NEW.account_number_bidx AND p.id <> NEW.id
             AND ((NEW.kind IN ('operating_bank','operating_mobile_money') AND p.kind = 'escrow_bank')
               OR (NEW.kind = 'escrow_bank' AND p.kind IN ('operating_bank','operating_mobile_money')))) THEN
        RAISE EXCEPTION 'An operating account cannot be an escrow account' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    *_trigger("trg_adm_partner_bank_rules", "adm_partner", "BEFORE INSERT OR UPDATE", "adm_partner_bank_rules"),
    # FR-ADM-005: a value that affects a release changes only with an approved request.
    """
    CREATE OR REPLACE FUNCTION adm_setting_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.affects_release AND (TG_OP = 'INSERT' OR NEW.value IS DISTINCT FROM OLD.value) THEN
        IF NEW.change_request_id IS NULL
           OR (TG_OP = 'UPDATE' AND NEW.change_request_id IS NOT DISTINCT FROM OLD.change_request_id)
           OR NOT EXISTS (SELECT 1 FROM adm_change_request c, core_approval_request r
                           WHERE c.id = NEW.change_request_id AND r.id = c.approval_request_id
                             AND r.status = 'approved') THEN
          RAISE EXCEPTION 'A value that affects a release needs a second administrator'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    *_trigger("trg_adm_setting_rules", "adm_setting", "BEFORE INSERT OR UPDATE", "adm_setting_rules"),
    # FR-ADM-002: a price row is closed, never rewritten, so quoted orders keep their price.
    """
    CREATE OR REPLACE FUNCTION adm_price_rules() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Prices are never deleted' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF NEW.price_amount IS DISTINCT FROM OLD.price_amount OR NEW.price_currency IS DISTINCT FROM OLD.price_currency
         OR NEW.valid_from IS DISTINCT FROM OLD.valid_from OR NEW.tier IS DISTINCT FROM OLD.tier
         OR (OLD.valid_to IS NOT NULL AND NEW.valid_to IS DISTINCT FROM OLD.valid_to) THEN
        RAISE EXCEPTION 'A price cannot be rewritten; set a new price' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    *_trigger("trg_adm_price_rules", "adm_price", "BEFORE UPDATE OR DELETE", "adm_price_rules"),
    *append_only("adm_fx_rate"),
]
