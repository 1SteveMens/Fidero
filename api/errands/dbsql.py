"""TSK rules enforced a second time in PostgreSQL (ADR-02; 02 section 6.13).

- tsk.checker_not_agent(): result_checked_by is Tenmina staff and not the agent (FR-TSK-004, RUL-23).
- tsk.agent_vetted(): an active agent has a current errand agent vetting (FR-TSK-003).
- esc.release_blockers() for errand steps: an instruction needs the step's receipt or acknowledgement and
  names the errand's agency as payee, never the agent (RUL-22, RUL-23, RUL-27).
"""

SQL = [
    """
    CREATE OR REPLACE FUNCTION tsk_checker_not_agent() RETURNS trigger AS $$
    DECLARE agent_person uuid;
    BEGIN
      IF NEW.result_checked_by_id IS NOT NULL
         AND NEW.result_checked_by_id IS DISTINCT FROM OLD.result_checked_by_id THEN
        SELECT a.person_id INTO agent_person FROM tsk_agent a WHERE a.id = NEW.agent_id;
        IF NEW.result_checked_by_id = agent_person OR NOT EXISTS (
            SELECT 1 FROM acc_role_grant g WHERE g.person_id = NEW.result_checked_by_id
               AND g.role IN ('CM','RV','AD') AND g.revoked_at IS NULL) THEN
          RAISE EXCEPTION 'FR-TSK-004: the result is checked by Tenmina staff, never the agent'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_tsk_checker_not_agent ON tsk_errand;",
    """CREATE TRIGGER trg_tsk_checker_not_agent BEFORE UPDATE ON tsk_errand
       FOR EACH ROW EXECUTE FUNCTION tsk_checker_not_agent();""",
    """
    CREATE OR REPLACE FUNCTION tsk_agent_vetted() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'active' AND NOT EXISTS (
          SELECT 1 FROM acc_vetting v WHERE v.id = NEW.vetting_id AND v.person_id = NEW.person_id
             AND v.kind = 'errand_agent' AND v.status = 'vetted' AND v.valid_until >= current_date) THEN
        RAISE EXCEPTION 'FR-TSK-003: an active agent needs a current errand agent vetting'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_tsk_agent_vetted ON tsk_agent;",
    """CREATE TRIGGER trg_tsk_agent_vetted BEFORE INSERT OR UPDATE ON tsk_agent
       FOR EACH ROW EXECUTE FUNCTION tsk_agent_vetted();""",
    """
    CREATE OR REPLACE FUNCTION tsk_instruction_rules() RETURNS trigger AS $$
    DECLARE s tsk_errand_step%ROWTYPE; e tsk_errand%ROWTYPE; agent_person uuid; payee_person uuid;
    BEGIN
      IF NEW.subject_type IS DISTINCT FROM 'errand_step' THEN
        RETURN NEW;
      END IF;
      IF TG_OP = 'UPDATE' AND NOT (NEW.status IN ('approved','sent') AND NEW.status IS DISTINCT FROM OLD.status) THEN
        RETURN NEW;
      END IF;
      SELECT * INTO s FROM tsk_errand_step WHERE id = NEW.subject_id;
      IF NOT FOUND OR (s.acknowledgement_evidence_id IS NULL AND s.receipt_evidence_id IS NULL) THEN
        RAISE EXCEPTION 'RUL-23: an official fee needs the step receipt or acknowledgement'
          USING ERRCODE = 'check_violation';
      END IF;
      SELECT * INTO e FROM tsk_errand WHERE id = s.errand_id;
      IF NEW.payee_id IS DISTINCT FROM e.agency_payee_id THEN
        RAISE EXCEPTION 'RUL-22: an official fee is paid only to the errand agency' USING ERRCODE = 'check_violation';
      END IF;
      SELECT a.person_id INTO agent_person FROM tsk_agent a WHERE a.id = e.agent_id;
      SELECT p.person_id INTO payee_person FROM esc_payee p WHERE p.id = NEW.payee_id;
      IF payee_person IS NOT NULL AND payee_person = agent_person THEN
        RAISE EXCEPTION 'RUL-27: the agent is paid by Tenmina, never from client money'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_tsk_instruction_rules ON esc_release_instruction;",
    """CREATE TRIGGER trg_tsk_instruction_rules BEFORE INSERT OR UPDATE ON esc_release_instruction
       FOR EACH ROW EXECUTE FUNCTION tsk_instruction_rules();""",
]
