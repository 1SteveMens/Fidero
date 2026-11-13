"""DSP rules enforced again in PostgreSQL (02 section 6.6).

- dsp_withdraw_rule(): 'withdrawn' only from open, awaiting_response or evidence (the transition table) and
  never with a decision recorded; 'closed' only with a decision and its decider.
- Statements and subject links are append-only.
"""
from core.dbsql import append_only

SQL = append_only("dsp_statement") + append_only("dsp_subject_link") + [
    """CREATE OR REPLACE FUNCTION dsp_dispute_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'withdrawn' AND OLD.status IS DISTINCT FROM 'withdrawn' THEN
        IF OLD.status NOT IN ('open', 'awaiting_response', 'evidence') OR NEW.decision <> '' THEN
          RAISE EXCEPTION 'A dispute is withdrawn only before the decision stage' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF NEW.status = 'closed' AND OLD.status IS DISTINCT FROM 'closed' THEN
        IF NEW.decision = '' OR NEW.decided_by_id IS NULL THEN
          RAISE EXCEPTION 'FR-DSP-004: a closed dispute has its decision, reasons and decider'
            USING ERRCODE = 'check_violation';
        END IF;
        IF EXISTS (SELECT 1 FROM dsp_party p WHERE p.dispute_id = NEW.id AND p.person_id = NEW.decided_by_id) THEN
          RAISE EXCEPTION 'FR-DSP-004: a party cannot decide its own dispute' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_dsp_dispute_rules ON dsp_dispute;",
    """CREATE TRIGGER trg_dsp_dispute_rules BEFORE UPDATE ON dsp_dispute
       FOR EACH ROW EXECUTE FUNCTION dsp_dispute_rules();""",
]
