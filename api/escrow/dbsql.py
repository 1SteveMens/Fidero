"""ESC rules enforced a second time in PostgreSQL (ADR-02; 02 sections 6.5,
6.11, 6.15, 6.16, 6.17). Function bodies and views must not contain the
text " ON " in capitals: core.dbsql.install() reads it as a table name.

- esc_confirmed_funds / esc_held_statement: held at the bank, derived from
  bank-confirmed events only (ADR-18, ADR-26). No stored balance exists.
- esc_payee_rules: the payee lock (RUL-28) and verification (RUL-22, RUL-31).
- esc_instruction_rules: a verified payee on every instruction (RUL-22),
  never the client, a relative or a representative, the right payee kind
  for the subject; at approval and sending, two staff approvals (RUL-05),
  the client's approval (RUL-11), no open condition (RUL-06), no freeze
  (RUL-15, RUL-32), no bank mismatch and never more than the escrow's own
  confirmed funds (RUL-34), the locked payee account after its cooling-off
  (RUL-28), and refunds only to source (RUL-29).
- esc_bank_event_rules: an event counts only under the escrow's own virtual
  account; the bank's facts and the source account are never edited.
- esc_escrow_rules: no release or cancellation while money is held
  (esc.unused_funds), the programme account matches, the conversion choice
  is fixed after a foreign currency deposit.
"""
from core.dbsql import append_only


def _trigger(name, table, when, fn):
    return [f"DROP TRIGGER IF EXISTS {name} ON {table};",
            f"CREATE TRIGGER {name} {when} ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}();"]


_LIVE = "('awaiting_client','pending_approval','approved','sent')"

SQL = [
    """CREATE OR REPLACE VIEW esc_confirmed_funds AS
    WITH va AS (
      SELECT id AS escrow_id, currency, programme_account_id, virtual_account_ref FROM esc_escrow
      UNION ALL
      SELECT escrow_id, currency, programme_account_id, virtual_account_ref FROM esc_fx_account
    )
    SELECT e.id AS escrow_id, e.kind, e.client_id, e.country_id, va.currency, va.programme_account_id,
           va.virtual_account_ref,
           COALESCE((SELECT SUM(b.amount) FROM esc_bank_event b
                      WHERE b.escrow_id = e.id AND b.currency = va.currency AND b.status = 'confirmed'
                        AND b.kind IN ('deposit','conversion_credit')), 0)
         - COALESCE((SELECT SUM(b.amount) FROM esc_bank_event b
                      WHERE b.escrow_id = e.id AND b.currency = va.currency AND b.status = 'confirmed'
                        AND b.kind IN ('release_confirmed','refund_confirmed','conversion_debit',
                                       'correction_debit')), 0) AS held_at_bank,
           COALESCE((SELECT SUM(i.amount) FROM esc_release_instruction i
                      WHERE i.escrow_id = e.id AND i.currency = va.currency
                        AND i.status IN ('awaiting_client','pending_approval','approved','sent')), 0)
             AS instructed_awaiting_bank,
           GREATEST(COALESCE((SELECT SUM(b.amount) FROM esc_bank_event b
                      WHERE b.escrow_id = e.id AND b.currency = va.currency AND b.status = 'confirmed'
                        AND b.kind = 'deposit' AND b.misdirected), 0)
                  - COALESCE((SELECT SUM(b.amount) FROM esc_bank_event b
                      WHERE b.escrow_id = e.id AND b.currency = va.currency AND b.status = 'confirmed'
                        AND b.kind = 'correction_debit'), 0), 0) AS awaiting_correction,
           (SELECT MAX(b.occurred_at) FROM esc_bank_event b
             WHERE b.escrow_id = e.id AND b.currency = va.currency AND b.status = 'confirmed') AS last_bank_event_at
      FROM esc_escrow e join va on va.escrow_id = e.id;""",
    """CREATE OR REPLACE VIEW esc_held_statement AS
       SELECT * FROM esc_confirmed_funds WHERE kind = 'held_funds';""",

    # ---------------------------------------------------------------- payees (RUL-22, RUL-28, RUL-31)
    """CREATE OR REPLACE FUNCTION esc_payee_rules() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Payees are never deleted' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF NEW.bank_name IS DISTINCT FROM OLD.bank_name OR NEW.account_number IS DISTINCT FROM OLD.account_number
         OR NEW.account_name IS DISTINCT FROM OLD.account_name THEN
        IF coalesce(current_setting('esc.apply_payee_change', true), '') = 'on' THEN
          IF NEW.account_version <= OLD.account_version THEN
            RAISE EXCEPTION 'RUL-28: a payee account change raises account_version' USING ERRCODE = 'check_violation';
          END IF;
        ELSIF OLD.verified_at IS NOT NULL OR EXISTS (SELECT 1 FROM esc_escrow_payee l WHERE l.payee_id = OLD.id) THEN
          RAISE EXCEPTION 'RUL-28: payee bank details change only through an approved payee change'
            USING ERRCODE = 'check_violation';
        END IF;
      ELSIF NEW.account_version <> OLD.account_version THEN
        RAISE EXCEPTION 'RUL-28: account_version changes only with the account' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.verification_status = 'verified' THEN
        IF NEW.legal_name_norm <> NEW.account_name_norm THEN
          RAISE EXCEPTION 'FR-ESC-015: account name does not match the payee' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.kind <> 'client_own_account' AND NOT EXISTS (
            SELECT 1 FROM acc_national_id_check c WHERE c.id = NEW.national_id_check_id AND c.result = 'match') THEN
          RAISE EXCEPTION 'RUL-31: the payee identity check has not matched' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.verification_status <> 'verified' AND NOT EXISTS (
            SELECT 1 FROM core_approval_request r WHERE r.id = NEW.approval_request_id AND r.status = 'approved'
               AND r.subject_type = 'payee_verification') THEN
          RAISE EXCEPTION 'FR-ESC-015: a payee is verified by two people' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_payee_rules", "esc_payee", "BEFORE UPDATE OR DELETE", "esc_payee_rules"),

    # ---------------------------------------------------------------- instructions (6.5 esc.release_blockers)
    f"""CREATE OR REPLACE FUNCTION esc_instruction_rules() RETURNS trigger AS $$
    DECLARE
      e esc_escrow%ROWTYPE;
      p esc_payee%ROWTYPE;
      dep esc_bank_event%ROWTYPE;
      held numeric;
      others numeric;
      misdirected numeric;
      used numeric;
      moving boolean;
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Instructions are never deleted' USING ERRCODE = 'insufficient_privilege';
      END IF;
      SELECT * INTO e FROM esc_escrow WHERE id = NEW.escrow_id;
      moving := TG_OP = 'UPDATE' AND NEW.status IN ('approved','sent') AND NEW.status IS DISTINCT FROM OLD.status;
      IF NEW.payee_id IS NOT NULL AND (TG_OP = 'INSERT' OR moving) THEN
        SELECT * INTO p FROM esc_payee WHERE id = NEW.payee_id;
        IF p.verification_status <> 'verified' OR p.legal_name_norm <> p.account_name_norm THEN
          RAISE EXCEPTION 'RUL-22: the payee is not verified with a matching account name'
            USING ERRCODE = 'check_violation';
        END IF;
        IF p.kind = 'client_own_account' OR p.person_id = e.client_id
           OR EXISTS (SELECT 1 FROM acc_family_member f WHERE f.client_id = e.client_id
                       AND f.person_id = p.person_id AND f.status <> 'anonymised')
           OR EXISTS (SELECT 1 FROM acc_representative_grant g WHERE g.client_id = e.client_id
                       AND g.representative_id = p.person_id AND g.status IN ('pending','active')) THEN
          RAISE EXCEPTION 'RUL-22: never the client, a relative or a representative' USING ERRCODE = 'check_violation';
        END IF;
        IF NOT (
             (NEW.subject_type IS NULL AND p.kind IN ('seller','developer'))
          OR (NEW.subject_type = 'milestone' AND p.kind IN ('contractor','developer','supplier'))
          OR (NEW.subject_type = 'offplan_stage' AND p.kind = 'developer')
          OR (NEW.subject_type = 'project_invoice' AND p.kind IN ('supplier','contractor','vendor','professional'))
          OR (NEW.subject_type = 'fee_invoice' AND p.kind = 'institution')
          OR (NEW.subject_type = 'care_visit' AND p.kind IN ('carer','agency'))
          OR (NEW.subject_type = 'errand_step' AND p.kind IN ('agency','institution'))
          OR (NEW.subject_type = 'repair' AND p.kind IN ('contractor','supplier'))
          OR (NEW.subject_type = 'event_vendor_payment' AND p.kind = 'vendor')
          OR (NEW.subject_type = 'premium' AND p.kind = 'insurer')) THEN
          RAISE EXCEPTION 'RUL-22: this payee kind cannot be paid for this subject' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF NEW.kind = 'cancel_refund' THEN
        SELECT * INTO dep FROM esc_bank_event WHERE id = NEW.refund_source_event_id;
        IF dep.escrow_id IS DISTINCT FROM NEW.escrow_id OR dep.kind <> 'deposit' OR dep.status <> 'confirmed' THEN
          RAISE EXCEPTION 'RUL-29: a refund names a confirmed deposit of this escrow' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF NOT moving THEN
        RETURN NEW;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM core_approval_request r WHERE r.id = NEW.approval_request_id
                      AND r.status = 'approved') THEN
        RAISE EXCEPTION 'RUL-05: two staff approvals are needed' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.kind IN ('release','partial_release','conversion') AND NEW.client_approved_at IS NULL
         AND NEW.standing_approval_id IS NULL THEN
        RAISE EXCEPTION 'RUL-11: the client has not approved' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.kind IN ('release','partial_release') AND EXISTS (
          SELECT 1 FROM esc_condition c WHERE c.escrow_id = NEW.escrow_id AND c.status = 'open'
             AND c.release_part = NEW.release_part) THEN
        RAISE EXCEPTION 'RUL-06: a condition of this release is open' USING ERRCODE = 'check_violation';
      END IF;
      IF EXISTS (SELECT 1 FROM esc_incident_freeze z WHERE z.escrow_id = NEW.escrow_id AND z.lifted_at IS NULL) THEN
        RAISE EXCEPTION 'RUL-15, RUL-32: the escrow is frozen' USING ERRCODE = 'check_violation';
      END IF;
      IF e.programme_account_id IS NULL OR e.virtual_account_ref IS NULL OR EXISTS (
          SELECT 1 FROM esc_bank_position bp WHERE bp.escrow_id = NEW.escrow_id AND bp.status = 'mismatch'
             AND bp.as_of = (SELECT max(x.as_of) FROM esc_bank_position x WHERE x.escrow_id = bp.escrow_id
                               AND x.currency = bp.currency AND x.status <> 'pending_check')) THEN
        RAISE EXCEPTION 'RUL-34: no virtual account, or the bank figure is a mismatch'
          USING ERRCODE = 'check_violation';
      END IF;
      SELECT f.held_at_bank, f.awaiting_correction INTO held, misdirected FROM esc_confirmed_funds f
       WHERE f.escrow_id = NEW.escrow_id AND f.currency = NEW.currency;
      SELECT COALESCE(SUM(i.amount), 0) INTO others FROM esc_release_instruction i
       WHERE i.escrow_id = NEW.escrow_id AND i.currency = NEW.currency AND i.id <> NEW.id AND i.status IN {_LIVE};
      IF NEW.amount > COALESCE(held, 0) - others - COALESCE(misdirected, 0) THEN
        RAISE EXCEPTION 'RUL-34: the instruction exceeds the escrow''s own confirmed funds'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.payee_id IS NOT NULL THEN
        IF NEW.payee_account_version <> p.account_version
           OR (p.cooling_off_until IS NOT NULL AND p.cooling_off_until > now())
           OR NOT EXISTS (SELECT 1 FROM esc_escrow_payee l WHERE l.escrow_id = NEW.escrow_id
                           AND l.payee_id = NEW.payee_id AND l.account_version = NEW.payee_account_version
                           AND l.ended_at IS NULL) THEN
          RAISE EXCEPTION 'RUL-28: the payee account is not locked on this escrow, or is cooling off'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF NEW.kind = 'cancel_refund' THEN
        SELECT COALESCE(SUM(i.amount), 0) INTO used FROM esc_release_instruction i
         WHERE i.refund_source_event_id = NEW.refund_source_event_id AND i.id <> NEW.id
           AND i.status IN ('awaiting_client','pending_approval','approved','sent','confirmed');
        IF NEW.amount > dep.amount - used THEN
          RAISE EXCEPTION 'RUL-29: the refund exceeds what is left of the deposit' USING ERRCODE = 'check_violation';
        END IF;
        IF (NOT dep.source_account_known OR dep.source_cannot_receive) AND NOT EXISTS (
            SELECT 1 FROM esc_payee_change c WHERE c.id = NEW.refund_change_id AND c.kind = 'refund_destination'
               AND c.status = 'applied' AND c.deposit_event_id = dep.id AND c.cooling_off_until <= now()) THEN
          RAISE EXCEPTION 'RUL-29: refund only to source unless the exception path is complete'
            USING ERRCODE = 'check_violation';
        END IF;
        IF dep.source_account_known AND NOT dep.source_cannot_receive AND NEW.refund_change_id IS NOT NULL THEN
          RAISE EXCEPTION 'RUL-29: this deposit goes back to its source' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_instruction_rules", "esc_release_instruction", "BEFORE INSERT OR UPDATE OR DELETE",
              "esc_instruction_rules"),

    # ---------------------------------------------------------------- bank events (RUL-34, FR-ESC-017)
    """CREATE OR REPLACE FUNCTION esc_bank_event_rules() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Bank events are never deleted' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF TG_OP = 'INSERT' THEN
        IF NOT EXISTS (SELECT 1 FROM esc_escrow e WHERE e.id = NEW.escrow_id
                         AND e.programme_account_id = NEW.programme_account_id
                         AND e.virtual_account_ref = NEW.virtual_account_ref AND e.currency = NEW.currency)
           AND NOT EXISTS (SELECT 1 FROM esc_fx_account f WHERE f.escrow_id = NEW.escrow_id
                         AND f.programme_account_id = NEW.programme_account_id
                         AND f.virtual_account_ref = NEW.virtual_account_ref AND f.currency = NEW.currency) THEN
          RAISE EXCEPTION 'RUL-34: the event is not under this escrow''s virtual account'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END IF;
      IF NEW.escrow_id IS DISTINCT FROM OLD.escrow_id OR NEW.kind IS DISTINCT FROM OLD.kind
         OR NEW.amount IS DISTINCT FROM OLD.amount OR NEW.currency IS DISTINCT FROM OLD.currency
         OR NEW.bank_reference IS DISTINCT FROM OLD.bank_reference
         OR NEW.virtual_account_ref IS DISTINCT FROM OLD.virtual_account_ref
         OR NEW.programme_account_id IS DISTINCT FROM OLD.programme_account_id
         OR NEW.source_bank_name IS DISTINCT FROM OLD.source_bank_name
         OR NEW.source_account_number IS DISTINCT FROM OLD.source_account_number
         OR NEW.source_account_name IS DISTINCT FROM OLD.source_account_name
         OR NEW.source_account_known IS DISTINCT FROM OLD.source_account_known
         OR NEW.source IS DISTINCT FROM OLD.source OR NEW.instruction_id IS DISTINCT FROM OLD.instruction_id
         OR NEW.misdirected IS DISTINCT FROM OLD.misdirected THEN
        RAISE EXCEPTION 'The bank''s facts are never edited; record a new event' USING ERRCODE = 'check_violation';
      END IF;
      IF OLD.status <> 'pending_check' AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'A checked bank event does not change status' USING ERRCODE = 'check_violation';
      END IF;
      IF OLD.source_cannot_receive AND NOT NEW.source_cannot_receive THEN
        RAISE EXCEPTION 'A returned refund stays recorded' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_bank_event_rules", "esc_bank_event", "BEFORE INSERT OR UPDATE OR DELETE",
              "esc_bank_event_rules"),

    # ---------------------------------------------------------------- escrows (RUL-34, RUL-36, RUL-29)
    """CREATE OR REPLACE FUNCTION esc_escrow_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.programme_account_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM esc_programme_account a WHERE a.id = NEW.programme_account_id
             AND a.country_id = NEW.country_id AND a.currency = NEW.currency) THEN
        RAISE EXCEPTION 'RUL-34: the programme account is for another country or currency'
          USING ERRCODE = 'check_violation';
      END IF;
      IF TG_OP = 'UPDATE' THEN
        IF NEW.status IN ('released','cancelled') AND NEW.status IS DISTINCT FROM OLD.status AND EXISTS (
            SELECT 1 FROM esc_confirmed_funds f WHERE f.escrow_id = NEW.id AND f.held_at_bank <> 0) THEN
          RAISE EXCEPTION 'RUL-29, RUL-36: money is still held; refund it to source first'
            USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.conversion_choice IS DISTINCT FROM OLD.conversion_choice AND EXISTS (
            SELECT 1 FROM esc_bank_event b WHERE b.escrow_id = NEW.id AND b.kind = 'deposit'
               AND b.status = 'confirmed' AND b.currency <> NEW.currency) THEN
          RAISE EXCEPTION 'RUL-36: the conversion choice is fixed after a foreign currency deposit'
            USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.virtual_account_ref IS NOT NULL AND NEW.virtual_account_ref IS DISTINCT FROM OLD.virtual_account_ref
           AND OLD.status <> 'proposed' THEN
          RAISE EXCEPTION 'RUL-34: an agreed escrow keeps its virtual account' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_escrow_rules", "esc_escrow", "BEFORE INSERT OR UPDATE", "esc_escrow_rules"),

    # ---------------------------------------------------------------- conditions (FR-ESC-005)
    """CREATE OR REPLACE FUNCTION esc_condition_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'closed' AND OLD.status = 'open' AND NOT EXISTS (
          SELECT 1 FROM evd_link l WHERE l.subject_type = 'escrow_condition' AND l.subject_id = NEW.id) THEN
        RAISE EXCEPTION 'FR-ESC-005: a condition closes only with evidence' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_condition_rules", "esc_condition", "BEFORE UPDATE", "esc_condition_rules"),

    # ---------------------------------------------------------------- the lock, quotes, observations
    """CREATE OR REPLACE FUNCTION esc_escrow_payee_rules() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' OR NEW.escrow_id <> OLD.escrow_id OR NEW.payee_id <> OLD.payee_id
         OR NEW.account_version <> OLD.account_version OR NEW.source <> OLD.source
         OR NEW.client_approved_at <> OLD.client_approved_at OR OLD.ended_at IS NOT NULL THEN
        RAISE EXCEPTION 'RUL-28: a payee lock is only ended, never edited' USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_escrow_payee_rules", "esc_escrow_payee", "BEFORE UPDATE OR DELETE", "esc_escrow_payee_rules"),
    """CREATE OR REPLACE FUNCTION esc_fx_quote_rules() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' OR OLD.accepted_at IS NOT NULL
         OR (to_jsonb(NEW) - 'accepted_at' - 'accepted_by_id' - 'updated_at' - 'row_version')
            <> (to_jsonb(OLD) - 'accepted_at' - 'accepted_by_id' - 'updated_at' - 'row_version') THEN
        RAISE EXCEPTION 'RUL-35: a quote is never edited; only its acceptance is recorded'
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_fx_quote_rules", "esc_fx_quote", "BEFORE UPDATE OR DELETE", "esc_fx_quote_rules"),
    """CREATE OR REPLACE FUNCTION esc_fx_observation_rules() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' OR OLD.checked_by_id IS NOT NULL
         OR (to_jsonb(NEW) - 'checked_by_id' - 'updated_at' - 'row_version')
            <> (to_jsonb(OLD) - 'checked_by_id' - 'updated_at' - 'row_version') THEN
        RAISE EXCEPTION 'FR-ESC-024: a collected rate is never edited' USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_fx_observation_rules", "esc_fx_rate_observation", "BEFORE UPDATE OR DELETE",
              "esc_fx_observation_rules"),
    """CREATE OR REPLACE FUNCTION esc_programme_account_rules() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'UPDATE' AND (NEW.account_number IS DISTINCT FROM OLD.account_number
          OR NEW.account_name IS DISTINCT FROM OLD.account_name OR NEW.currency IS DISTINCT FROM OLD.currency
          OR NEW.bank_partner_id IS DISTINCT FROM OLD.bank_partner_id) THEN
        RAISE EXCEPTION 'RUL-34: a new account is a new row with the same approvals' USING ERRCODE = 'check_violation';
      END IF;
      IF EXISTS (SELECT 1 FROM adm_partner p WHERE p.account_number_bidx = NEW.account_number_bidx
                  AND p.kind IN ('operating_bank','operating_mobile_money')) THEN
        RAISE EXCEPTION 'RUL-27: an operating account is never an escrow account' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.status = 'active' AND NOT EXISTS (SELECT 1 FROM core_approval_request r
           WHERE r.id = NEW.approval_request_id AND r.status = 'approved') THEN
        RAISE EXCEPTION 'FR-ADM-003: a second administrator approves the account' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_programme_account_rules", "esc_programme_account", "BEFORE INSERT OR UPDATE",
              "esc_programme_account_rules"),
    """CREATE OR REPLACE FUNCTION esc_fx_account_rules() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM esc_programme_account a, esc_escrow e
                      WHERE a.id = NEW.programme_account_id AND e.id = NEW.escrow_id AND a.country_id = e.country_id
                        AND a.currency = NEW.currency AND NEW.currency <> e.currency) THEN
        RAISE EXCEPTION 'RUL-34: a foreign currency account matches its programme account' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    *_trigger("trg_esc_fx_account_rules", "esc_fx_account", "BEFORE INSERT OR UPDATE", "esc_fx_account_rules"),
    *append_only("esc_acceptance"),
]
