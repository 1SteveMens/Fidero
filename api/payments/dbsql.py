"""PAY rules enforced a second time in PostgreSQL (ADR-02, ADR-03, FR-PAY-002, FR-PAY-008)."""
from core.dbsql import append_only

SQL = [
    # FR-PAY-002: no full card number in any column that a provider or a person can fill.
    # A 13 to 19 digit run that passes the Luhn check is refused.
    """
    CREATE OR REPLACE FUNCTION pay_luhn(digits text) RETURNS boolean AS $$
    DECLARE s int := 0; d int; alt boolean := false; i int;
    BEGIN
      FOR i IN REVERSE length(digits)..1 LOOP
        d := substr(digits, i, 1)::int;
        IF alt THEN
          d := d * 2;
          IF d > 9 THEN d := d - 9; END IF;
        END IF;
        s := s + d;
        alt := NOT alt;
      END LOOP;
      RETURN s % 10 = 0;
    END $$ LANGUAGE plpgsql IMMUTABLE;
    """,
    """
    CREATE OR REPLACE FUNCTION pay_no_card_numbers() RETURNS trigger AS $$
    DECLARE m text[]; col text; val text;
    BEGIN
      FOREACH col IN ARRAY TG_ARGV LOOP
        val := to_jsonb(NEW) ->> col;
        IF val IS NOT NULL THEN
          FOR m IN SELECT regexp_matches(replace(val, ' ', ''), '[0-9]{13,19}', 'g') LOOP
            IF pay_luhn(m[1]) THEN
              RAISE EXCEPTION 'A card number cannot be stored (FR-PAY-002)' USING ERRCODE = 'check_violation';
            END IF;
          END LOOP;
        END IF;
      END LOOP;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_pay_payment_no_pan ON pay_fee_payment;",
    """CREATE TRIGGER trg_pay_payment_no_pan BEFORE INSERT OR UPDATE ON pay_fee_payment FOR EACH ROW
       EXECUTE FUNCTION pay_no_card_numbers('card_brand', 'card_last4', 'wallet_last4',
                                            'wallet_network', 'failure_code', 'failure_message');""",
    "DROP TRIGGER IF EXISTS trg_pay_refund_no_pan ON pay_refund;",
    """CREATE TRIGGER trg_pay_refund_no_pan BEFORE INSERT OR UPDATE ON pay_refund FOR EACH ROW
       EXECUTE FUNCTION pay_no_card_numbers('failure_message', 'reason');""",
    "DROP TRIGGER IF EXISTS trg_pay_receipt_no_pan ON pay_receipt;",
    """CREATE TRIGGER trg_pay_receipt_no_pan BEFORE INSERT ON pay_receipt FOR EACH ROW
       EXECUTE FUNCTION pay_no_card_numbers('method_detail', 'description');""",
    # The money facts of a payment never change after it is recorded (ADR-03).
    """
    CREATE OR REPLACE FUNCTION pay_payment_facts_fixed() RETURNS trigger AS $$
    BEGIN
      IF NEW.amount IS DISTINCT FROM OLD.amount OR NEW.currency IS DISTINCT FROM OLD.currency
         OR NEW.purpose IS DISTINCT FROM OLD.purpose OR NEW.order_id IS DISTINCT FROM OLD.order_id
         OR NEW.invoice_id IS DISTINCT FROM OLD.invoice_id OR NEW.payer_id IS DISTINCT FROM OLD.payer_id
         OR NEW.method IS DISTINCT FROM OLD.method
         OR NEW.source_account_number IS DISTINCT FROM OLD.source_account_number
         OR NEW.source_account_name IS DISTINCT FROM OLD.source_account_name
         OR NEW.source_bank_name IS DISTINCT FROM OLD.source_bank_name
         OR (OLD.provider_ref IS NOT NULL AND NEW.provider_ref IS DISTINCT FROM OLD.provider_ref) THEN
        RAISE EXCEPTION 'The amount, payer, link and source of a fee payment cannot change'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_pay_payment_facts_fixed ON pay_fee_payment;",
    """CREATE TRIGGER trg_pay_payment_facts_fixed BEFORE UPDATE ON pay_fee_payment
       FOR EACH ROW EXECUTE FUNCTION pay_payment_facts_fixed();""",
    # FR-PAY-008: refunds never exceed the payment less earlier refunds, are tied to one payment,
    # and keep their amount and currency.
    """
    CREATE OR REPLACE FUNCTION pay_refund_within_payment() RETURNS trigger AS $$
    DECLARE paid numeric; other numeric; cur text;
    BEGIN
      IF TG_OP = 'UPDATE' AND (NEW.payment_id IS DISTINCT FROM OLD.payment_id
         OR NEW.amount IS DISTINCT FROM OLD.amount OR NEW.currency IS DISTINCT FROM OLD.currency) THEN
        RAISE EXCEPTION 'A refund cannot be redirected or resized' USING ERRCODE = 'check_violation';
      END IF;
      SELECT amount, currency INTO paid, cur FROM pay_fee_payment WHERE id = NEW.payment_id FOR UPDATE;
      IF NEW.currency <> cur THEN
        RAISE EXCEPTION 'A refund is in the currency of the payment' USING ERRCODE = 'check_violation';
      END IF;
      SELECT coalesce(sum(amount), 0) INTO other FROM pay_refund
       WHERE payment_id = NEW.payment_id AND id <> NEW.id
         AND status IN ('requested', 'approved', 'processing', 'completed', 'failed');
      IF NEW.status IN ('requested', 'approved', 'processing', 'completed', 'failed')
         AND other + NEW.amount > paid THEN
        RAISE EXCEPTION 'Refunds cannot exceed the payment (FR-PAY-008)' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_pay_refund_within_payment ON pay_refund;",
    """CREATE TRIGGER trg_pay_refund_within_payment BEFORE INSERT OR UPDATE ON pay_refund
       FOR EACH ROW EXECUTE FUNCTION pay_refund_within_payment();""",
    # FR-PAY-003: receipts and credit notes are records, never edited. Settlement lines are facts too.
    *append_only("pay_receipt"),
    *append_only("pay_settlement_line"),
    # ADR-03: no balance or wallet column in a fee table (also checked by a test over the whole schema).
]
