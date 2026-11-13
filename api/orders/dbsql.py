"""ORD rules enforced a second time in PostgreSQL (ADR-02)."""
from core.dbsql import append_only

SQL = [
    # FR-ORD-002: once an order leaves draft its price is fixed; the amount charged equals the amount shown.
    """
    CREATE OR REPLACE FUNCTION ord_price_locked() RETURNS trigger AS $$
    BEGIN
      IF OLD.status <> 'draft' AND NEW.status <> 'draft' AND (
           NEW.price_amount IS DISTINCT FROM OLD.price_amount
        OR NEW.price_currency IS DISTINCT FROM OLD.price_currency
        OR NEW.local_price_amount IS DISTINCT FROM OLD.local_price_amount
        OR NEW.local_price_currency IS DISTINCT FROM OLD.local_price_currency
        OR NEW.kind IS DISTINCT FROM OLD.kind
        OR NEW.client_id IS DISTINCT FROM OLD.client_id) THEN
        RAISE EXCEPTION 'The price and kind of a submitted order cannot change' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_ord_price_locked ON ord_order;",
    """CREATE TRIGGER trg_ord_price_locked BEFORE UPDATE ON ord_order
       FOR EACH ROW EXECUTE FUNCTION ord_price_locked();""",
    # FR-ORD-003: a terms acceptance is a record, never edited.
    *append_only("ord_terms_acceptance"),
]
