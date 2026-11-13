"""CARE rules enforced a second time in PostgreSQL (ADR-02; 02 section 6.12).

- care.carer_vetted(): an active carer has a vetted carer vetting that has not expired (FR-CARE-002).
- care.confirmers_may_confirm(): every confirmer is an active family member of the client marked
  may_confirm_visits (FR-CARE-001).
- care.plan_assigns_active_carer(): a plan is given or started with an active carer only (FR-CARE-002).
- care.visit_confirmed_needs_confirmation(): 'confirmed' needs a confirmation with confirmed_at, and a
  check-in and check-out at the address or with their flags cleared, unless a reviewer decided (RUL-23).
- care.confirmer_allowed() and care.staff_not_carer(): the confirmer is a named confirmer and never the
  carer; a call is recorded by staff who is not the carer (ADR-20).
- esc.release_blockers() for care visits: an instruction for a visit that is not confirmed, for a carer
  Tenmina pays itself, or to anyone but the visit's carer or agency is refused (RUL-23, RUL-27).
"""

SQL = [
    """
    CREATE OR REPLACE FUNCTION care_carer_vetted() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'active' AND NOT EXISTS (
          SELECT 1 FROM acc_vetting v WHERE v.id = NEW.vetting_id AND v.person_id = NEW.person_id
             AND v.kind = 'carer' AND v.status = 'vetted' AND v.valid_until >= current_date) THEN
        RAISE EXCEPTION 'FR-CARE-002: an active carer needs a current carer vetting'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_care_carer_vetted ON care_carer;",
    """CREATE TRIGGER trg_care_carer_vetted BEFORE INSERT OR UPDATE ON care_carer
       FOR EACH ROW EXECUTE FUNCTION care_carer_vetted();""",
    """
    CREATE OR REPLACE FUNCTION care_plan_rules() RETURNS trigger AS $$
    DECLARE bad integer;
    BEGIN
      IF cardinality(NEW.confirmers) < 1 THEN
        RAISE EXCEPTION 'FR-CARE-001: a plan names at least one confirmer' USING ERRCODE = 'check_violation';
      END IF;
      SELECT count(*) INTO bad FROM unnest(NEW.confirmers) AS c(id)
       WHERE NOT EXISTS (SELECT 1 FROM acc_family_member f WHERE f.id = c.id AND f.client_id = NEW.client_id
                           AND f.status = 'active' AND f.may_confirm_visits);
      IF bad > 0 AND (TG_OP = 'INSERT' OR NEW.confirmers IS DISTINCT FROM OLD.confirmers) THEN
        RAISE EXCEPTION 'FR-CARE-001: every confirmer is an active family member who may confirm visits'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.carer_id IS NOT NULL AND (TG_OP = 'INSERT' OR NEW.carer_id IS DISTINCT FROM OLD.carer_id
          OR (NEW.status = 'active' AND OLD.status IS DISTINCT FROM 'active')) THEN
        IF NOT EXISTS (SELECT 1 FROM care_carer c WHERE c.id = NEW.carer_id AND c.status = 'active') THEN
          RAISE EXCEPTION 'FR-CARE-002: only an active, vetted carer is assigned' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_care_plan_rules ON care_plan;",
    """CREATE TRIGGER trg_care_plan_rules BEFORE INSERT OR UPDATE ON care_plan
       FOR EACH ROW EXECUTE FUNCTION care_plan_rules();""",
    """
    CREATE OR REPLACE FUNCTION care_checkin_ok(ci_id uuid) RETURNS boolean AS $$
      SELECT EXISTS (SELECT 1 FROM mob_checkin ci WHERE ci.id = ci_id
               AND NOT EXISTS (SELECT 1 FROM mob_fraud_flag f WHERE f.checkin_id = ci.id
                                AND f.status IN ('open','upheld'))
               AND (ci.within_radius OR EXISTS (SELECT 1 FROM mob_fraud_flag f WHERE f.checkin_id = ci.id
                                                  AND f.status = 'cleared')));
    $$ LANGUAGE sql STABLE;
    """,
    """
    CREATE OR REPLACE FUNCTION care_visit_confirmed() RETURNS trigger AS $$
    DECLARE c care_confirmation%ROWTYPE;
    BEGIN
      IF NEW.status = 'confirmed' AND OLD.status IN ('checked_out','unconfirmed','disputed') THEN
        SELECT * INTO c FROM care_confirmation WHERE visit_id = NEW.id;
        IF NOT FOUND OR c.confirmed_at IS NULL THEN
          RAISE EXCEPTION 'RUL-23: a visit is confirmed only with a recorded confirmation'
            USING ERRCODE = 'check_violation';
        END IF;
        IF c.method IS DISTINCT FROM 'reviewer'
           AND NOT (care_checkin_ok(NEW.checkin_id) AND care_checkin_ok(NEW.checkout_id)) THEN
          RAISE EXCEPTION 'RUL-23: the check-in and check-out must be at the address or cleared by a reviewer'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_care_visit_confirmed ON care_visit;",
    """CREATE TRIGGER trg_care_visit_confirmed BEFORE UPDATE ON care_visit
       FOR EACH ROW EXECUTE FUNCTION care_visit_confirmed();""",
    """
    CREATE OR REPLACE FUNCTION care_confirmation_rules() RETURNS trigger AS $$
    DECLARE carer_person uuid; plan_confirmers uuid[];
    BEGIN
      -- no explicit joins here: core.dbsql takes the word after the last upper-case join keyword as the table
      SELECT c.person_id, p.confirmers INTO carer_person, plan_confirmers
        FROM care_visit v, care_carer c, care_plan p
       WHERE v.id = NEW.visit_id AND c.id = v.carer_id AND p.id = v.plan_id;
      IF NEW.confirmed_by_family_member_id IS NOT NULL THEN
        IF NOT (NEW.confirmed_by_family_member_id = ANY(plan_confirmers)) THEN
          RAISE EXCEPTION 'ADR-20: only a named confirmer confirms a visit' USING ERRCODE = 'check_violation';
        END IF;
        IF EXISTS (SELECT 1 FROM acc_family_member f WHERE f.id = NEW.confirmed_by_family_member_id
                    AND f.person_id = carer_person) THEN
          RAISE EXCEPTION 'RUL-23: the carer never confirms their own visit' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF NEW.recorded_by_staff_id IS NOT NULL AND (NEW.recorded_by_staff_id = carer_person OR NOT EXISTS (
          SELECT 1 FROM acc_role_grant g WHERE g.person_id = NEW.recorded_by_staff_id
             AND g.role IN ('CM','RV','AD') AND g.revoked_at IS NULL)) THEN
        RAISE EXCEPTION 'ADR-20: a call is recorded by Tenmina staff who is not the carer'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.call_checked_by_id = carer_person OR NEW.reviewer_id = carer_person THEN
        RAISE EXCEPTION 'FR-CARE-004: the carer cannot check or decide their own visit'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_care_confirmation_rules ON care_confirmation;",
    """CREATE TRIGGER trg_care_confirmation_rules BEFORE INSERT OR UPDATE ON care_confirmation
       FOR EACH ROW EXECUTE FUNCTION care_confirmation_rules();""",
    """
    CREATE OR REPLACE FUNCTION care_instruction_rules() RETURNS trigger AS $$
    DECLARE v care_visit%ROWTYPE; c care_carer%ROWTYPE;
    BEGIN
      IF NEW.subject_type IS DISTINCT FROM 'care_visit' THEN
        RETURN NEW;
      END IF;
      IF TG_OP = 'UPDATE' AND NOT (NEW.status IN ('approved','sent') AND NEW.status IS DISTINCT FROM OLD.status) THEN
        RETURN NEW;
      END IF;
      SELECT * INTO v FROM care_visit WHERE id = NEW.subject_id;
      IF NOT FOUND OR v.status NOT IN ('confirmed','instructed','paid') OR v.confirmed_at IS NULL THEN
        RAISE EXCEPTION 'RUL-23: visit-not-confirmed' USING ERRCODE = 'check_violation';
      END IF;
      SELECT * INTO c FROM care_carer WHERE id = v.carer_id;
      IF c.pay_route <> 'held_funds' THEN
        RAISE EXCEPTION 'RUL-27: a carer Tenmina contracts is never paid from client money'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.payee_id IS DISTINCT FROM c.payee_id THEN
        RAISE EXCEPTION 'RUL-22: a visit pays only its carer or agency' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_care_instruction_rules ON esc_release_instruction;",
    """CREATE TRIGGER trg_care_instruction_rules BEFORE INSERT OR UPDATE ON esc_release_instruction
       FOR EACH ROW EXECUTE FUNCTION care_instruction_rules();""",
]
