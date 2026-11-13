def test_dbg(seeded, gh):
    from countries import services as cty
    from countries.selectors import current_config
    from administration.models import ConfigVersion
    cfg = current_config(gh)
    print("BLOCK", cty.publication_blockers(cfg))
    for k, pk in cfg.data["refs"]["config_versions"].items():
        cv = ConfigVersion.objects.get(pk=pk)
        print("REF", k, cv.product_line, cv.version, cv.state)
    for cv in ConfigVersion.objects.filter(country=gh, kind__in=["case_template","report_template"]).order_by("kind","product_line","version"):
        print("CV", cv.kind, cv.product_line, cv.version, cv.state)
