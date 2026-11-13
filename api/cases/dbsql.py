"""CASE rules enforced again in PostgreSQL (ADR-02; 02 sections 6.5, 6.7, 6.15).

- case.task_done_requires_evidence(): a task becomes done only when every kind in required_evidence has an
  evd_link on the task (FR-CASE-004).
- case.site_visit_risk(): a site visit is assigned only with a valid risk screen that does not say "do not
  visit", and with a second person when the plot is disputed or the screen asks for two (RUL-17).
- case.search_task_source(): a search task is done only with a usable official search request (RUL-30).
- case.search_staff_only(): who submits, receives or confirms a search holds a case manager or reviewer grant
  and none of the runner, seller, developer, client or agent roles (RUL-30, ADR-25).
- Status messages, messages, risk screens and copy checks are append-only; so is safety.incident.
"""
from core.dbsql import append_only

SQL = append_only("case_status_message") + append_only("case_message") + append_only("case_risk_screen") \
    + append_only("case_search_copy_check") + [
    """CREATE OR REPLACE FUNCTION case_is_search_staff(p uuid, cid uuid) RETURNS boolean AS $$
      SELECT p IS NOT NULL
        AND EXISTS (SELECT 1 FROM acc_role_grant g WHERE g.person_id = p AND g.revoked_at IS NULL
                     AND g.role IN ('CM', 'RV') AND (g.country_id IS NULL OR g.country_id = cid))
        AND NOT EXISTS (SELECT 1 FROM acc_role_grant g WHERE g.person_id = p AND g.revoked_at IS NULL
                     AND g.role IN ('RN', 'SE', 'DV', 'CL', 'CE') AND (g.country_id IS NULL OR g.country_id = cid));
    $$ LANGUAGE sql STABLE;""",
    """CREATE OR REPLACE FUNCTION case_search_usable(sr case_search_request) RETURNS boolean AS $$
      SELECT (sr.channel = 'online_portal' AND sr.status IN ('result_received', 'confirmed'))
          OR (sr.channel = 'registry_office' AND sr.status = 'confirmed');
    $$ LANGUAGE sql IMMUTABLE;""",
    """CREATE OR REPLACE FUNCTION case_task_rules() RETURNS trigger AS $$
    DECLARE k text; scr case_risk_screen; disputed boolean;
    BEGIN
      IF NEW.status = 'done' AND OLD.status IS DISTINCT FROM 'done' THEN
        FOR k IN SELECT jsonb_array_elements_text(NEW.required_evidence) LOOP
          IF NOT EXISTS (SELECT 1 FROM evd_link l WHERE l.subject_type = 'task' AND l.subject_id = NEW.id
                          AND l.role = k) THEN
            RAISE EXCEPTION 'FR-CASE-004: task % is missing evidence %', NEW.step_key, k
              USING ERRCODE = 'check_violation';
          END IF;
        END LOOP;
        IF NEW.search_kind = 'result' AND NOT EXISTS (
            SELECT 1 FROM case_search_request s WHERE s.case_id = NEW.case_id
              AND (NEW.step_key <> 'fresh_search' OR s.task_id = NEW.id) AND case_search_usable(s)) THEN
          RAISE EXCEPTION 'RUL-30: search task % has no usable official result', NEW.step_key
            USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.search_kind = 'lodge' AND NOT EXISTS (
            SELECT 1 FROM case_search_request s WHERE s.case_id = NEW.case_id AND s.status <> 'rejected') THEN
          RAISE EXCEPTION 'RUL-30: no official search lodged for task %', NEW.step_key
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF NEW.site_visit AND NEW.assignee_id IS NOT NULL AND NEW.status IN ('open', 'in_progress')
         AND (NEW.assignee_id IS DISTINCT FROM OLD.assignee_id
              OR NEW.second_assignee_id IS DISTINCT FROM OLD.second_assignee_id) THEN
        SELECT * INTO scr FROM case_risk_screen r WHERE r.task_id = NEW.id ORDER BY r.created_at DESC LIMIT 1;
        IF scr.id IS NULL OR scr.valid_until < now() OR scr.outcome = 'do_not_visit' THEN
          RAISE EXCEPTION 'RUL-17: a site visit needs a valid risk screen before assignment'
            USING ERRCODE = 'check_violation';
        END IF;
        SELECT coalesce(c.risk_flag, false) OR coalesce(a.disputed_flag, false) INTO disputed
          FROM case_case c LEFT JOIN geo_asset a on a.id = c.asset_id WHERE c.id = NEW.case_id;
        IF (disputed OR scr.people_required >= 2) AND NEW.second_assignee_id IS NULL THEN
          RAISE EXCEPTION 'RUL-17: this site visit needs two people' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_case_task_rules ON case_task;",
    "CREATE TRIGGER trg_case_task_rules BEFORE UPDATE ON case_task FOR EACH ROW EXECUTE FUNCTION case_task_rules();",
    """CREATE OR REPLACE FUNCTION case_search_staff_only() RETURNS trigger AS $$
    BEGIN
      IF NOT case_is_search_staff(NEW.submitted_by_id, NEW.country_id)
         OR (NEW.result_received_by_id IS NOT NULL AND NOT case_is_search_staff(NEW.result_received_by_id,
                                                                                NEW.country_id))
         OR (NEW.confirmed_by_id IS NOT NULL AND NOT case_is_search_staff(NEW.confirmed_by_id, NEW.country_id)) THEN
        RAISE EXCEPTION 'RUL-30: only Tenmina case managers or reviewers handle official searches'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_case_search_staff_only ON case_search_request;",
    """CREATE TRIGGER trg_case_search_staff_only BEFORE INSERT OR UPDATE ON case_search_request FOR EACH ROW
       EXECUTE FUNCTION case_search_staff_only();""",
    # safety.incident is in its own schema, so it is set up through EXECUTE (02 6.7, 10.9).
    """DO $$ BEGIN
      IF to_regclass('safety.incident') IS NOT NULL THEN
        EXECUTE 'DROP TRIGGER IF EXISTS trg_safety_incident_append_only ' || 'ON safety.incident';
        EXECUTE 'CREATE TRIGGER trg_safety_incident_append_only BEFORE UPDATE OR DELETE ' || 'ON safety.incident '
             || 'FOR EACH ROW EXECUTE FUNCTION core_append_only()';
      END IF;
    END $$;""",
]
