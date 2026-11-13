"""LST rules enforced again in PostgreSQL (02 section 6.6, ADR-02).

- lst_publish_rule(): a listing goes to 'live' from 'in_verification' only when its report is released, green,
  for the same plot and no older than adm_setting 'listing_report_max_age_days' (RUL-12). Into 'live' or
  'reserved' from any state only with a released report and a badge that has not expired (RUL-13).
- lst_removal is append-only (FR-LST-008: the reason stays on record).
"""
from core.dbsql import append_only

SQL = append_only("lst_removal") + [
    """CREATE OR REPLACE FUNCTION lst_publish_rule() RETURNS trigger AS $$
    DECLARE r rpt_report; asset uuid; max_age int;
    BEGIN
      IF NEW.status IN ('live', 'reserved') AND OLD.status IS DISTINCT FROM NEW.status THEN
        SELECT * INTO r FROM rpt_report WHERE id = NEW.report_id;
        IF r.id IS NULL OR r.status <> 'released' THEN
          RAISE EXCEPTION 'RUL-12: a listing goes live only with a released report' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.badge_expires_at IS NULL OR NEW.badge_expires_at <= now() THEN
          RAISE EXCEPTION 'RUL-13: the badge has expired' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'in_verification' THEN
          SELECT c.asset_id INTO asset FROM case_case c WHERE c.id = r.case_id;
          IF asset IS DISTINCT FROM NEW.asset_id THEN
            RAISE EXCEPTION 'RUL-12: the report is for a different plot' USING ERRCODE = 'check_violation';
          END IF;
          IF r.overall_verdict IS DISTINCT FROM 'green' THEN
            RAISE EXCEPTION 'RUL-12: only a green report can be listed' USING ERRCODE = 'check_violation';
          END IF;
          SELECT (s.value #>> '{}')::int INTO max_age FROM adm_setting s
           WHERE s.key = 'listing_report_max_age_days' AND (s.country_id = NEW.country_id OR s.country_id IS NULL)
           ORDER BY s.country_id NULLS LAST LIMIT 1;
          IF r.released_at < now() - make_interval(days => coalesce(max_age, 90)) THEN
            RAISE EXCEPTION 'RUL-12: the report is older than the allowed age' USING ERRCODE = 'check_violation';
          END IF;
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_lst_publish_rule ON lst_listing;",
    """CREATE TRIGGER trg_lst_publish_rule BEFORE UPDATE ON lst_listing
       FOR EACH ROW EXECUTE FUNCTION lst_publish_rule();""",
]
