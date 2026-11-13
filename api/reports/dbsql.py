"""RPT rules enforced again in PostgreSQL (ADR-02; 02 sections 6.5, 6.15).

- rpt.freeze_released(): a released report never changes, except status to 'superseded' (FR-RPT-010).
- rpt.verdict_rule(): overall_verdict 'green' is refused while a section in the verdict rule is red (RUL-02).
- rpt.scope_locked(): section 12 keeps the locked scope text; nobody edits it by hand (RUL-04).
- rpt.licence_valid(): a signature needs a verified licence in date at signing (RUL-20).
- rpt.parties_checked(): approved or released only when every active case party has a finished national
  identity check (RUL-31, FR-ACC-013).
- rpt.recheck_no_link(): a re-check assignee held no task, signature or report approval on the case, is not
  its client or a party, and holds a verified licence in date until due_at (RUL-32, RUL-20).
- Draws, hash checks and anonymised copies are append-only; re-checks are never deleted.
"""
from core.dbsql import append_only

SQL = append_only("rpt_recheck_draw") + append_only("rpt_hash_check") + append_only("rpt_anonymised_copy") + [
    """CREATE OR REPLACE FUNCTION rpt_freeze_released() RETURNS trigger AS $$
    BEGIN
      IF OLD.status IN ('released', 'superseded') THEN
        IF NOT (OLD.status = 'released' AND NEW.status = 'superseded')
           OR NEW.overall_verdict IS DISTINCT FROM OLD.overall_verdict
           OR NEW.pdf_sha256 IS DISTINCT FROM OLD.pdf_sha256
           OR NEW.pdf_evidence_id IS DISTINCT FROM OLD.pdf_evidence_id
           OR NEW.released_at IS DISTINCT FROM OLD.released_at
           OR NEW.scope_text_version_id IS DISTINCT FROM OLD.scope_text_version_id THEN
          RAISE EXCEPTION 'FR-RPT-010: a released report never changes' USING ERRCODE = 'insufficient_privilege';
        END IF;
      END IF;
      IF NEW.overall_verdict = 'green' AND EXISTS (
          SELECT 1 FROM rpt_section s WHERE s.report_id = NEW.id AND s.in_verdict_rule AND s.verdict = 'red') THEN
        RAISE EXCEPTION 'RUL-02: the overall verdict cannot be green while a section from 4 to 10 is red'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.status IN ('approved', 'released') AND OLD.status IS DISTINCT FROM NEW.status AND EXISTS (
          SELECT 1 FROM case_party p LEFT JOIN acc_national_id_check c on c.id = p.national_id_check_id
           WHERE p.case_id = NEW.case_id AND p.status = 'active'
             AND (c.id IS NULL OR c.result IN ('pending', 'unavailable'))) THEN
        RAISE EXCEPTION 'RUL-31: every party needs a finished national identity check'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_rpt_report_rules ON rpt_report;",
    "CREATE TRIGGER trg_rpt_report_rules BEFORE UPDATE ON rpt_report FOR EACH ROW EXECUTE FUNCTION rpt_freeze_released();",
    "DROP TRIGGER IF EXISTS trg_rpt_report_no_delete ON rpt_report;",
    "CREATE TRIGGER trg_rpt_report_no_delete BEFORE DELETE ON rpt_report FOR EACH ROW EXECUTE FUNCTION core_append_only();",
    """CREATE OR REPLACE FUNCTION rpt_section_rules() RETURNS trigger AS $$
    DECLARE st text; ov text;
    BEGIN
      SELECT status, overall_verdict INTO st, ov FROM rpt_report WHERE id = NEW.report_id;
      IF TG_OP = 'UPDATE' AND st IN ('released', 'superseded') THEN
        RAISE EXCEPTION 'FR-RPT-010: a released report never changes' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF TG_OP = 'UPDATE' AND OLD.locked AND st <> 'draft' AND NEW.findings IS DISTINCT FROM OLD.findings THEN
        RAISE EXCEPTION 'RUL-04: the scope statement is locked' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF NEW.in_verdict_rule AND NEW.verdict = 'red' AND ov = 'green' THEN
        RAISE EXCEPTION 'RUL-02: reset the green overall verdict before a section goes red'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_rpt_section_rules ON rpt_section;",
    """CREATE TRIGGER trg_rpt_section_rules BEFORE INSERT OR UPDATE ON rpt_section FOR EACH ROW
       EXECUTE FUNCTION rpt_section_rules();""",
    """CREATE OR REPLACE FUNCTION rpt_licence_valid() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'UPDATE' THEN
        IF NEW.signed_at IS DISTINCT FROM OLD.signed_at OR NEW.signer_id IS DISTINCT FROM OLD.signer_id
           OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256 OR NEW.licence_id IS DISTINCT FROM OLD.licence_id
           OR (OLD.invalidated_at IS NOT NULL AND NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at) THEN
          RAISE EXCEPTION 'A signature never changes; it can only be marked invalid once'
            USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM acc_professional_licence l WHERE l.id = NEW.licence_id AND l.status = 'verified'
                      AND l.person_id = NEW.signer_id AND l.role = NEW.role
                      AND l.expires_on >= (NEW.signed_at AT TIME ZONE 'UTC')::date) THEN
        RAISE EXCEPTION 'RUL-20: the signer needs a verified licence for this role, in date'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_rpt_licence_valid ON rpt_signature;",
    """CREATE TRIGGER trg_rpt_licence_valid BEFORE INSERT OR UPDATE ON rpt_signature FOR EACH ROW
       EXECUTE FUNCTION rpt_licence_valid();""",
    "DROP TRIGGER IF EXISTS trg_rpt_signature_no_delete ON rpt_signature;",
    """CREATE TRIGGER trg_rpt_signature_no_delete BEFORE DELETE ON rpt_signature FOR EACH ROW
       EXECUTE FUNCTION core_append_only();""",
    """CREATE OR REPLACE FUNCTION rpt_recheck_no_link() RETURNS trigger AS $$
    BEGIN
      IF NEW.assignee_id IS NOT NULL AND (TG_OP = 'INSERT' OR NEW.assignee_id IS DISTINCT FROM OLD.assignee_id) THEN
        IF EXISTS (SELECT 1 FROM case_task t WHERE t.case_id = NEW.case_id
                     AND (t.assignee_id = NEW.assignee_id OR t.second_assignee_id = NEW.assignee_id))
           OR EXISTS (SELECT 1 FROM rpt_signature s JOIN rpt_report r on r.id = s.report_id
                       WHERE r.case_id = NEW.case_id AND s.signer_id = NEW.assignee_id)
           OR EXISTS (SELECT 1 FROM core_approval a JOIN core_approval_request q on q.id = a.request_id
                       JOIN rpt_report r on r.id = q.subject_id
                       WHERE q.subject_type = 'report_release' AND r.case_id = NEW.case_id
                         AND a.approver_id = NEW.assignee_id)
           OR EXISTS (SELECT 1 FROM case_case c WHERE c.id = NEW.case_id
                       AND (c.client_id = NEW.assignee_id OR c.case_manager_id = NEW.assignee_id))
           OR EXISTS (SELECT 1 FROM case_party p WHERE p.case_id = NEW.case_id AND p.person_id = NEW.assignee_id) THEN
          RAISE EXCEPTION 'RUL-32: the re-checker has a link to the case' USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM acc_professional_licence l WHERE l.id = NEW.licence_id
                        AND l.person_id = NEW.assignee_id AND l.status = 'verified'
                        AND l.expires_on >= coalesce(NEW.due_at, now())::date) THEN
          RAISE EXCEPTION 'RUL-20: the re-checker needs a verified licence in date until the due date'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_rpt_recheck_no_link ON rpt_recheck;",
    """CREATE TRIGGER trg_rpt_recheck_no_link BEFORE INSERT OR UPDATE ON rpt_recheck FOR EACH ROW
       EXECUTE FUNCTION rpt_recheck_no_link();""",
    "DROP TRIGGER IF EXISTS trg_rpt_recheck_no_delete ON rpt_recheck;",
    "CREATE TRIGGER trg_rpt_recheck_no_delete BEFORE DELETE ON rpt_recheck FOR EACH ROW EXECUTE FUNCTION core_append_only();",
]
