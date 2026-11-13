"""Rules the database enforces a second time (02 section 6.9)."""

SQL = [
    # cty.config_immutable(): a published configuration never changes; publishing needs
    # an approved two-person request and a publication time.
    """
    CREATE OR REPLACE FUNCTION cty_config_rules() RETURNS trigger AS $$
    BEGIN
      IF OLD.status IN ('published','superseded') AND (NEW.data IS DISTINCT FROM OLD.data
          OR NEW.version IS DISTINCT FROM OLD.version OR NEW.country_id IS DISTINCT FROM OLD.country_id) THEN
        RAISE EXCEPTION 'A published country configuration cannot change' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.status = 'published' AND OLD.status <> 'published' THEN
        IF NEW.published_at IS NULL OR NEW.approval_request_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM core_approval_request r WHERE r.id = NEW.approval_request_id AND r.status = 'approved') THEN
          RAISE EXCEPTION 'Publishing needs a second administrator' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_cty_config_rules ON cty_country_config;",
    """CREATE TRIGGER trg_cty_config_rules BEFORE UPDATE ON cty_country_config
       FOR EACH ROW EXECUTE FUNCTION cty_config_rules();""",
    # An active country has a published configuration and an approved activation.
    """
    CREATE OR REPLACE FUNCTION cty_country_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'active' AND OLD.status IN ('manual_phase','validating','draft','paused') THEN
        IF NEW.current_config_id IS NULL OR NEW.activation_request_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM core_approval_request r WHERE r.id = NEW.activation_request_id AND r.status = 'approved') THEN
          RAISE EXCEPTION 'A country is activated only by two administrators' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_cty_country_rules ON cty_country;",
    """CREATE TRIGGER trg_cty_country_rules BEFORE UPDATE ON cty_country
       FOR EACH ROW EXECUTE FUNCTION cty_country_rules();""",
]
