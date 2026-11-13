"""EVT rules enforced a second time in PostgreSQL (ADR-02; 02 section 6.13). Function bodies must not contain
the text " ON " in capitals: core.dbsql.install() reads it as a table name.

- evt_budget_not_exceeded(): proposed to paid vendor payments never exceed the event budget, unless the client
  raises the budget first (recorded in budget_history).
- evt_payment_to_verified_vendor(): a payment past `proposed` names a verified vendor with a verified payee
  (RUL-22).
"""


def _trigger(name, table, when, fn):
    return [f"DROP TRIGGER IF EXISTS {name} ON {table};",
            f"CREATE TRIGGER {name} {when} ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}();"]


_COMMITTED = "('proposed','evidenced','client_approved','instructed','paid')"

SQL = [
    f"""CREATE OR REPLACE FUNCTION evt_budget_not_exceeded() RETURNS trigger AS $$
    DECLARE total numeric; budget numeric;
    BEGIN
      IF NEW.status NOT IN {_COMMITTED} THEN RETURN NEW; END IF;
      SELECT e.budget_amount INTO budget FROM evt_event e WHERE e.id = NEW.event_id;
      SELECT COALESCE(SUM(p.amount), 0) INTO total FROM evt_vendor_payment p
       WHERE p.event_id = NEW.event_id AND p.id <> NEW.id AND p.status IN {_COMMITTED};
      IF total + NEW.amount > budget THEN
        RAISE EXCEPTION 'Vendor payments would exceed the event budget' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_evt_budget_not_exceeded", "evt_vendor_payment", "BEFORE INSERT OR UPDATE",
              "evt_budget_not_exceeded"),
    f"""CREATE OR REPLACE FUNCTION evt_budget_covers_commitments() RETURNS trigger AS $$
    DECLARE total numeric;
    BEGIN
      IF NEW.budget_amount IS NOT DISTINCT FROM OLD.budget_amount THEN RETURN NEW; END IF;
      SELECT COALESCE(SUM(p.amount), 0) INTO total FROM evt_vendor_payment p
       WHERE p.event_id = NEW.id AND p.status IN {_COMMITTED};
      IF NEW.budget_amount < total THEN
        RAISE EXCEPTION 'The budget cannot be less than the vendor payments committed' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_evt_budget_covers_commitments", "evt_event", "BEFORE UPDATE", "evt_budget_covers_commitments"),
    """CREATE OR REPLACE FUNCTION evt_payment_to_verified_vendor() RETURNS trigger AS $$
    BEGIN
      IF NEW.status NOT IN ('evidenced','client_approved','instructed') THEN RETURN NEW; END IF;
      IF NOT EXISTS (SELECT 1 FROM evt_vendor v, esc_payee y
                      WHERE v.id = NEW.vendor_id AND v.status = 'verified' AND y.id = v.payee_id
                        AND y.verification_status = 'verified' AND y.kind = 'vendor') THEN
        RAISE EXCEPTION 'An event payment goes only to a verified vendor''s verified payee'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_evt_payment_to_verified_vendor", "evt_vendor_payment", "BEFORE INSERT OR UPDATE",
              "evt_payment_to_verified_vendor"),
]
