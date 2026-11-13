"""Current scope statement and client terms shown before payment (FR-ORD-003, RUL-04).

The texts are locked and versioned. ADM will own them (`adm_locked_text_version`);
until it provides `administration.selectors.locked_text(country, kind)`, the
country configuration `legal_texts.<kind>` = {"version", "text"} is read, then
the defaults below. The order stores the version strings the client accepted.
"""
DEFAULTS = {
    "client_terms": {
        "version": "client-terms-2026-11-v1",
        "title": "Client terms",
        "text": (
            "Tenmina checks and reports. It does not hold your money: a licensed bank does. "
            "You pay Tenmina's fee for the work, whatever the verdict. A fee refund goes back only to the card "
            "or mobile money wallet you paid with. Full terms: [TO VERIFY, lawyer to finalise]."
        ),
    },
    "scope_statement": {
        "version": "scope-statement-2026-11-v1",
        "title": "What the report covers",
        "text": (
            "The report records what the registry, the site visit, the survey overlay, the family or stool "
            "consent and a licensed lawyer found on the dates shown. It is not a title guarantee or insurance. "
            "It does not cover anything that is not in an official record or that changed after those dates. "
            "[TO VERIFY, lawyer to finalise]."
        ),
    },
}


def locked_text(country, kind: str) -> dict:
    try:
        from administration import selectors as adm

        fn = getattr(adm, "locked_text", None)
        if fn:
            found = fn(country, kind)
            if found:
                return found
    except ImportError:  # pragma: no cover
        pass
    from countries.selectors import config

    own = config(country, f"legal_texts.{kind}")
    if own and own.get("version"):
        return {"title": DEFAULTS.get(kind, {}).get("title", kind), **own}
    return dict(DEFAULTS[kind])


def current(country) -> dict:
    terms = locked_text(country, "client_terms")
    scope = locked_text(country, "scope_statement")
    return {"terms": terms, "scope": scope,
            "terms_version": terms["version"], "scope_version": scope["version"]}
