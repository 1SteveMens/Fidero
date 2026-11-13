"""RAT rules enforced again in PostgreSQL.

- rat_rating_fixed(): a rating's score, rater, subject and comment text never change; moderation changes only
  the comment's visibility (FR-RAT-004). Ratings are never deleted.
- rat_outcome is append-only.
"""
from core.dbsql import append_only

SQL = append_only("rat_outcome") + [
    """CREATE OR REPLACE FUNCTION rat_rating_fixed() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Ratings are not deleted' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF NEW.score IS DISTINCT FROM OLD.score OR NEW.rater_id IS DISTINCT FROM OLD.rater_id
         OR NEW.subject_id IS DISTINCT FROM OLD.subject_id OR NEW.comment IS DISTINCT FROM OLD.comment THEN
        RAISE EXCEPTION 'FR-RAT-004: a rating and its comment text never change' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_rat_rating_fixed ON rat_rating;",
    """CREATE TRIGGER trg_rat_rating_fixed BEFORE UPDATE OR DELETE ON rat_rating
       FOR EACH ROW EXECUTE FUNCTION rat_rating_fixed();""",
]
