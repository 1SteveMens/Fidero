"""PMG rules enforced a second time in PostgreSQL (ADR-02; 02 section 6.13). Function bodies must not
contain the text " ON " in capitals: core.dbsql.install() reads it as a table name.

- pmg_rent_account_is_owners(): the rent account is the owner's own verified account (RUL-24).
- pmg_two_quotes_before_approval(): quotes ready or later needs two quotes from different contractors,
  unless a reviewer recorded an exception or the country allows one quote for small repairs (FR-PMG-004).
- pmg_repair_escrow_amount(): the repair escrow's agreed amount is the approved quote's amount.
- pmg_rent_received_is_bank_fact(): rent marked received or partial names a statement line of an
  `owner_rent` statement (ADR-03: the figure is the bank's, never Tenmina's).
"""


def _trigger(name, table, when, fn):
    return [f"DROP TRIGGER IF EXISTS {name} ON {table};",
            f"CREATE TRIGGER {name} {when} ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}();"]


SQL = [
    """CREATE OR REPLACE FUNCTION pmg_rent_account_is_owners() RETURNS trigger AS $$
    DECLARE changed boolean;
    BEGIN
      IF NEW.rent_account_id IS NULL THEN RETURN NEW; END IF;
      IF TG_OP = 'INSERT' THEN changed := true;
      ELSE changed := NEW.rent_account_id IS DISTINCT FROM OLD.rent_account_id; END IF;
      IF changed AND NOT EXISTS (SELECT 1 FROM acc_bank_account a
                                  WHERE a.id = NEW.rent_account_id AND a.holder_id = NEW.owner_id
                                    AND a.verification_status = 'verified' AND a.name_match = 'matched') THEN
        RAISE EXCEPTION 'rent-destination-invalid: the rent account must be the owner''s own verified account'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_pmg_rent_account_is_owners", "pmg_managed_property", "BEFORE INSERT OR UPDATE",
              "pmg_rent_account_is_owners"),
    """CREATE OR REPLACE FUNCTION pmg_two_quotes_before_approval() RETURNS trigger AS $$
    DECLARE n int; small_max numeric; over_max int;
    BEGIN
      IF NEW.status NOT IN ('quotes_ready','approved') OR NEW.status IS NOT DISTINCT FROM OLD.status THEN
        RETURN NEW;
      END IF;
      SELECT COUNT(DISTINCT q.contractor_id) INTO n FROM pmg_repair_quote q
       WHERE q.repair_id = NEW.id AND q.status IN ('received','approved','declined');
      IF n >= 2 THEN RETURN NEW; END IF;
      IF n >= 1 AND NEW.single_quote_exception_by_id IS NOT NULL THEN RETURN NEW; END IF;
      SELECT NULLIF(c.data->'pmg'->>'repair_single_quote_max_amount', '')::numeric INTO small_max
        FROM cty_country_config c WHERE c.country_id = NEW.country_id AND c.status = 'published'
       ORDER BY c.version DESC LIMIT 1;
      IF n >= 1 AND small_max IS NOT NULL THEN
        SELECT COUNT(*) INTO over_max FROM pmg_repair_quote q
         WHERE q.repair_id = NEW.id AND q.status IN ('received','approved','declined') AND q.quote_amount > small_max;
        IF over_max = 0 THEN RETURN NEW; END IF;
      END IF;
      RAISE EXCEPTION 'A repair needs two quotes from different vetted contractors before approval'
        USING ERRCODE = 'check_violation';
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_pmg_two_quotes", "pmg_repair", "BEFORE UPDATE", "pmg_two_quotes_before_approval"),
    """CREATE OR REPLACE FUNCTION pmg_repair_escrow_amount() RETURNS trigger AS $$
    BEGIN
      IF NEW.escrow_id IS NULL OR NEW.approved_quote_id IS NULL THEN RETURN NEW; END IF;
      IF NOT EXISTS (SELECT 1 FROM esc_escrow e, pmg_repair_quote q
                      WHERE e.id = NEW.escrow_id AND q.id = NEW.approved_quote_id AND q.repair_id = NEW.id
                        AND e.kind = 'repair' AND e.agreed_amount = q.quote_amount
                        AND e.currency = q.quote_currency) THEN
        RAISE EXCEPTION 'The repair escrow must be for the approved quote amount' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_pmg_repair_escrow_amount", "pmg_repair", "BEFORE INSERT OR UPDATE", "pmg_repair_escrow_amount"),
    """CREATE OR REPLACE FUNCTION pmg_rent_received_is_bank_fact() RETURNS trigger AS $$
    BEGIN
      IF NEW.statement_line_id IS NULL THEN RETURN NEW; END IF;
      IF NOT EXISTS (SELECT 1 FROM esc_statement_line l JOIN esc_statement_file f
                       ON_PLACEHOLDER f.id = l.file_id
                      WHERE l.id = NEW.statement_line_id AND f.account_kind = 'owner_rent' AND l.kind = 'credit') THEN
        RAISE EXCEPTION 'Rent is received only from a credit line of the owner''s rent account statement'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""".replace("ON_PLACEHOLDER", "on"),
    *_trigger("trg_pmg_rent_received_is_bank_fact", "pmg_rent_period", "BEFORE INSERT OR UPDATE",
              "pmg_rent_received_is_bank_fact"),
]
