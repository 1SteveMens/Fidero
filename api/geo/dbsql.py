"""GEO rules enforced a second time in PostgreSQL (ADR-02).

- Boundary versions, overlay features, overlay results and satellite images
  are append-only: a boundary is never edited, a new version is added.
- Every stored boundary and layer feature is a valid polygon in SRID 4326.
- An asset can only point at one of its own boundary versions.
- A layer version's content (layer, number, file hash, features) never changes;
  only its status moves from active to superseded.
- An incomplete overlay run never proposes green (TC-GEO-002-02).
"""
from core.dbsql import append_only


def _check(table, name, expr):
    return f"""
    DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
        ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr});
      END IF;
    END $$;
    """


SQL = [
    *append_only("geo_boundary_version"),
    *append_only("geo_overlay_feature"),
    *append_only("geo_overlay_result"),
    *append_only("geo_satellite_image"),
    _check("geo_boundary_version", "geo_boundary_valid", "ST_IsValid(geom) AND ST_SRID(geom) = 4326"),
    _check("geo_boundary_version", "geo_boundary_area_positive", "area_sqm > 0"),
    _check("geo_overlay_feature", "geo_feature_valid", "ST_IsValid(geom) AND ST_SRID(geom) = 4326"),
    _check("geo_overlay_result", "geo_result_outcome", "outcome IN ('inside','near','clear')"),
    _check("geo_overlay_result", "geo_result_share", "affected_share >= 0 AND affected_share <= 1"),
    _check("geo_overlay_run", "geo_run_verdict",
           "proposed_verdict IS NULL OR proposed_verdict IN ('red','amber','green')"),
    _check("geo_overlay_run", "geo_run_not_green_when_incomplete",
           "NOT (status IN ('incomplete','failed') AND proposed_verdict = 'green')"),
    _check("geo_overlap_flag", "geo_overlap_not_self", "asset_id <> other_asset_id"),
    _check("geo_overlap_flag", "geo_overlap_resolved_by",
           "status NOT IN ('confirmed','dismissed') OR (resolved_by_id IS NOT NULL AND resolution_note <> '')"),
    _check("geo_monitoring_alert", "geo_alert_resolved_by",
           "status <> 'resolved' OR (resolved_by_id IS NOT NULL AND resolution <> '')"),
    _check("geo_asset", "geo_asset_type", "type IN ('plot','building','offplan_unit','managed_property')"),
    """
    CREATE OR REPLACE FUNCTION geo_asset_current_boundary() RETURNS trigger AS $$
    BEGIN
      IF NEW.current_boundary_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM geo_boundary_version b WHERE b.id = NEW.current_boundary_id AND b.asset_id = NEW.id) THEN
        RAISE EXCEPTION 'An asset can only use one of its own boundary versions' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_geo_asset_current_boundary ON geo_asset;",
    """CREATE TRIGGER trg_geo_asset_current_boundary BEFORE INSERT OR UPDATE ON geo_asset
       FOR EACH ROW EXECUTE FUNCTION geo_asset_current_boundary();""",
    """
    CREATE OR REPLACE FUNCTION geo_layer_version_fixed() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Overlay layer versions are kept for traceability' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF NEW.layer_id <> OLD.layer_id OR NEW.version <> OLD.version OR NEW.sha256 <> OLD.sha256
         OR NEW.feature_count <> OLD.feature_count OR NEW.source <> OLD.source
         OR NEW.evidence_id IS DISTINCT FROM OLD.evidence_id THEN
        RAISE EXCEPTION 'An overlay layer version cannot be changed; load a new version'
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_geo_layer_version_fixed ON geo_overlay_layer_version;",
    """CREATE TRIGGER trg_geo_layer_version_fixed BEFORE UPDATE OR DELETE ON geo_overlay_layer_version
       FOR EACH ROW EXECUTE FUNCTION geo_layer_version_fixed();""",
]
