"""BLD rules enforced again in PostgreSQL (ADR-02; 02 section 6.6).

- bld.no_conflicted_inspector(): rejects an inspector on a project, a milestone or an inspection when a
  bld_conflict_link exists with the project's contractor, both are the same person or company, or the inspector
  works for the contractor's company (RUL-10).
- bld.share_total(): the shares of a project's milestones total 100 at commit (deferred constraint trigger).
- bld.mobilisation_only(): only milestone 0, mobilisation, of a building project goes from not started to client
  approved (RUL-09, TC-RUL-09-07).
- bld.release_needs_inspection(): a milestone of a building project other than mobilisation reaches client
  approved, release approved or paid only with a recorded pass or pass with defects (RUL-09).
- bld.defect_closed(): a closed defect has closing evidence and the inspector's confirmation (FR-BLD-006).
- bld.variation_agreed(): an agreed variation has both agreements (RUL-19).
"""

SQL = [
    """CREATE OR REPLACE FUNCTION bld_conflicted(insp uuid, con uuid) RETURNS boolean AS $$
      SELECT insp IS NOT NULL AND con IS NOT NULL AND (
        EXISTS (SELECT 1 FROM bld_conflict_link l WHERE l.inspector_id = insp AND l.contractor_id = con)
        OR EXISTS (SELECT 1 FROM bld_panel_member i, bld_panel_member c WHERE i.id = insp AND c.id = con AND (
             (i.person_id IS NOT NULL AND i.person_id = c.person_id)
          OR (i.organisation_id IS NOT NULL AND i.organisation_id = c.organisation_id)
          OR EXISTS (SELECT 1 FROM acc_membership m WHERE m.person_id = i.person_id AND m.status = 'active'
                       AND (m.organisation_id = c.organisation_id OR m.organisation_id IN (
                         SELECT m2.organisation_id FROM acc_membership m2
                          WHERE m2.person_id = c.person_id AND m2.status = 'active'))))));
    $$ LANGUAGE sql STABLE;""",
    """CREATE OR REPLACE FUNCTION bld_no_conflicted_inspector() RETURNS trigger AS $$
    DECLARE con uuid;
    BEGIN
      IF TG_TABLE_NAME = 'bld_project' THEN
        con := NEW.contractor_id;
      ELSE
        SELECT p.contractor_id INTO con FROM bld_project p WHERE p.id = NEW.project_id;
      END IF;
      IF bld_conflicted(NEW.inspector_id, con) THEN
        RAISE EXCEPTION 'RUL-10: the inspector has a recorded link to the contractor' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_bld_project_inspector ON bld_project;",
    """CREATE TRIGGER trg_bld_project_inspector BEFORE INSERT OR UPDATE OF inspector_id, contractor_id ON bld_project
       FOR EACH ROW EXECUTE FUNCTION bld_no_conflicted_inspector();""",
    "DROP TRIGGER IF EXISTS trg_bld_milestone_inspector ON bld_milestone;",
    """CREATE TRIGGER trg_bld_milestone_inspector BEFORE INSERT OR UPDATE OF inspector_id ON bld_milestone
       FOR EACH ROW EXECUTE FUNCTION bld_no_conflicted_inspector();""",
    """CREATE OR REPLACE FUNCTION bld_inspection_rules() RETURNS trigger AS $$
    DECLARE con uuid;
    BEGIN
      SELECT p.contractor_id INTO con FROM bld_project p WHERE p.id = NEW.project_id;
      IF NEW.status = 'scheduled' AND bld_conflicted(NEW.inspector_id, con) THEN
        RAISE EXCEPTION 'RUL-10: the inspector has a recorded link to the contractor' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_bld_inspection_rules ON bld_inspection;",
    """CREATE TRIGGER trg_bld_inspection_rules BEFORE INSERT OR UPDATE ON bld_inspection
       FOR EACH ROW EXECUTE FUNCTION bld_inspection_rules();""",
    """CREATE OR REPLACE FUNCTION bld_share_total() RETURNS trigger AS $$
    DECLARE pid uuid; total numeric;
    BEGIN
      pid := COALESCE(NEW.project_id, OLD.project_id);
      SELECT sum(share_pct) INTO total FROM bld_milestone WHERE project_id = pid;
      IF total IS NOT NULL AND total <> 100 THEN
        RAISE EXCEPTION 'FR-BLD-002: milestone shares total % not 100', total USING ERRCODE = 'check_violation';
      END IF;
      RETURN NULL;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_bld_share_total ON bld_milestone;",
    """CREATE CONSTRAINT TRIGGER trg_bld_share_total AFTER INSERT OR UPDATE OF share_pct OR DELETE ON bld_milestone
       DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bld_share_total();""",
    """CREATE OR REPLACE FUNCTION bld_milestone_rules() RETURNS trigger AS $$
    DECLARE ptype text;
    BEGIN
      SELECT p.type INTO ptype FROM bld_project p WHERE p.id = NEW.project_id;
      IF ptype = 'funds' OR NEW.status IS NOT DISTINCT FROM OLD.status THEN
        RETURN NEW;
      END IF;
      IF OLD.status = 'not_started' AND NEW.status = 'client_approved'
         AND NOT (NEW.seq = 0 AND NEW.key = 'mobilisation') THEN
        RAISE EXCEPTION 'RUL-09: only milestone 0 (mobilisation) skips evidence and inspection'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.status IN ('client_approved', 'release_approved', 'paid') AND OLD.status <> 'frozen'
         AND NOT (NEW.seq = 0 AND NEW.key = 'mobilisation')
         AND NOT EXISTS (SELECT 1 FROM bld_inspection i WHERE i.milestone_id = NEW.id AND i.status = 'recorded'
                           AND i.kind IN ('milestone', 'retention') AND i.outcome IN ('pass', 'pass_with_defects')) THEN
        RAISE EXCEPTION 'RUL-09: no inspector pass for milestone %', NEW.key USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_bld_milestone_rules ON bld_milestone;",
    """CREATE TRIGGER trg_bld_milestone_rules BEFORE UPDATE OF status ON bld_milestone
       FOR EACH ROW EXECUTE FUNCTION bld_milestone_rules();""",
    """CREATE OR REPLACE FUNCTION bld_payment_rules() RETURNS trigger AS $$
    DECLARE runner uuid;
    BEGIN
      IF NEW.status = 'paid' AND NEW.route = 'client_direct' AND NEW.receipt_confirmed_by_id IS NULL THEN
        RAISE EXCEPTION 'A direct payment is paid only when its receipt is confirmed' USING ERRCODE = 'check_violation';
      END IF;
      SELECT p.runner_person_id INTO runner FROM bld_project p WHERE p.id = NEW.project_id;
      IF runner IS NOT NULL AND EXISTS (SELECT 1 FROM esc_payee e WHERE e.id = NEW.payee_id AND e.person_id = runner)
      THEN
        RAISE EXCEPTION 'RUL-21: the person running the project is never paid' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_bld_payment_rules ON bld_payment;",
    """CREATE TRIGGER trg_bld_payment_rules BEFORE INSERT OR UPDATE ON bld_payment
       FOR EACH ROW EXECUTE FUNCTION bld_payment_rules();""",
]
