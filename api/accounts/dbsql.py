"""ACC rules enforced a second time in PostgreSQL (ADR-02, 02 sections 6.4
and 6.15). Function bodies must not contain the text " ON " in capitals:
core.dbsql.install() reads it as a table name."""

_HONORIFICS = "'MR','MRS','MS','MISS','DR','PROF','REV','NANA','TOGBE','ALHAJI','HAJIA'"
_SUFFIXES = "'LTD','LIMITED','PLC','CO','COMPANY','ENTERPRISE','ENTERPRISES'"

SQL = [
    # 9.2: the SQL twin of accounts.normalise.normalise_name().
    f"""CREATE OR REPLACE FUNCTION acc_normalise_name(n text) RETURNS text AS $$
      SELECT coalesce(string_agg(w, ' ' ORDER BY i), '')
        FROM unnest(regexp_split_to_array(
               trim(regexp_replace(upper(coalesce(n, '')), '[^A-Z0-9 ]+', ' ', 'g')), '\\s+'))
             WITH ORDINALITY AS t(w, i)
       WHERE w <> '' AND w NOT IN ({_SUFFIXES}, {_HONORIFICS});
    $$ LANGUAGE sql IMMUTABLE;""",

    # 6.4 acc.no_money_roles() and the rights rules: release rights (RR) and
    # payment rights (PY) need an approved request of two administrators;
    # RR never sits with a client, family member, carer or errand agent,
    # contractor or a client's representative; PY never with a contracted
    # professional (FR-PRO-005).
    """CREATE OR REPLACE FUNCTION acc_role_grant_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.revoked_at IS NOT NULL THEN
        RETURN NEW;
      END IF;
      IF NEW.role IN ('RR', 'PY') AND (NEW.approval_request_id IS NULL OR NOT EXISTS (
          SELECT 1 FROM core_approval_request r
           WHERE r.id = NEW.approval_request_id AND r.status = 'approved'
             AND r.subject_type = CASE WHEN NEW.role = 'RR' THEN 'release_rights_grant'
                                       ELSE 'payment_rights_grant' END)) THEN
        RAISE EXCEPTION 'Release and payment rights need the approval of two administrators'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.role = 'RR' AND (EXISTS (
          SELECT 1 FROM acc_role_grant g
           WHERE g.person_id = NEW.person_id AND g.id <> NEW.id AND g.revoked_at IS NULL
             AND g.role IN ('CL', 'FM', 'CE', 'CT')
             AND (g.country_id IS NULL OR NEW.country_id IS NULL OR g.country_id = NEW.country_id))
          OR EXISTS (SELECT 1 FROM acc_representative_grant rg
                      WHERE rg.representative_id = NEW.person_id AND rg.status = 'active')) THEN
        RAISE EXCEPTION 'Release rights cannot sit with a client, relative, representative, carer or contractor'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.role IN ('CL', 'FM', 'CE', 'CT') AND EXISTS (
          SELECT 1 FROM acc_role_grant g
           WHERE g.person_id = NEW.person_id AND g.id <> NEW.id AND g.revoked_at IS NULL AND g.role = 'RR'
             AND (g.country_id IS NULL OR NEW.country_id IS NULL OR g.country_id = NEW.country_id)) THEN
        RAISE EXCEPTION 'A person with release rights cannot hold this role' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.role = 'PY' AND EXISTS (
          SELECT 1 FROM acc_role_grant g
           WHERE g.person_id = NEW.person_id AND g.id <> NEW.id AND g.revoked_at IS NULL
             AND g.role IN ('LW', 'SV', 'RN', 'IN', 'QS', 'CE')) THEN
        RAISE EXCEPTION 'Payment rights cannot sit with a contracted professional' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.role IN ('LW', 'SV', 'RN', 'IN', 'QS', 'CE') AND EXISTS (
          SELECT 1 FROM acc_role_grant g
           WHERE g.person_id = NEW.person_id AND g.id <> NEW.id AND g.revoked_at IS NULL AND g.role = 'PY') THEN
        RAISE EXCEPTION 'A person with payment rights cannot hold a contracted role' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_acc_role_grant_rules ON acc_role_grant;",
    """CREATE TRIGGER trg_acc_role_grant_rules BEFORE INSERT OR UPDATE ON acc_role_grant
       FOR EACH ROW EXECUTE FUNCTION acc_role_grant_rules();""",

    # 6.4 acc.bank_account_holder_name() and acc.bank_account_change_resets().
    """CREATE OR REPLACE FUNCTION acc_bank_account_rules() RETURNS trigger AS $$
    DECLARE holder_name text;
    BEGIN
      IF TG_OP = 'UPDATE' AND (NEW.account_number IS DISTINCT FROM OLD.account_number
          OR NEW.account_name IS DISTINCT FROM OLD.account_name)
          AND OLD.verification_status IN ('verified', 'pending') THEN
        NEW.verification_status := 'pending';
      END IF;
      IF NEW.name_match = 'matched' AND (TG_OP = 'INSERT' OR OLD.name_match IS DISTINCT FROM 'matched'
          OR NEW.account_name IS DISTINCT FROM OLD.account_name
          OR (NEW.verification_status = 'verified' AND OLD.verification_status <> 'verified')) THEN
        SELECT full_name INTO holder_name FROM acc_person WHERE id = NEW.holder_id;
        IF acc_normalise_name(NEW.account_name) <> acc_normalise_name(holder_name) THEN
          RAISE EXCEPTION 'The account name does not match the holder' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_acc_bank_account_rules ON acc_bank_account;",
    """CREATE TRIGGER trg_acc_bank_account_rules BEFORE INSERT OR UPDATE ON acc_bank_account
       FOR EACH ROW EXECUTE FUNCTION acc_bank_account_rules();""",

    # 6.15: a national identity check's result, reference and the number and
    # name it was run for never change once the result is final.
    """CREATE OR REPLACE FUNCTION acc_national_id_check_rules() RETURNS trigger AS $$
    BEGIN
      IF NEW.id_number_bidx IS DISTINCT FROM OLD.id_number_bidx
         OR NEW.subject_name_bidx IS DISTINCT FROM OLD.subject_name_bidx
         OR NEW.subject_role IS DISTINCT FROM OLD.subject_role THEN
        RAISE EXCEPTION 'The checked number, name and role cannot change' USING ERRCODE = 'check_violation';
      END IF;
      IF OLD.result IN ('match', 'no_match', 'not_found') AND (
           NEW.result IS DISTINCT FROM OLD.result
           OR NEW.provider_reference IS DISTINCT FROM OLD.provider_reference
           OR NEW.response_sha256 IS DISTINCT FROM OLD.response_sha256
           OR NEW.checked_at IS DISTINCT FROM OLD.checked_at
           OR NEW.checked_by_id IS DISTINCT FROM OLD.checked_by_id) THEN
        RAISE EXCEPTION 'A national identity check result cannot change' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;""",
    "DROP TRIGGER IF EXISTS trg_acc_national_id_check_rules ON acc_national_id_check;",
    """CREATE TRIGGER trg_acc_national_id_check_rules BEFORE UPDATE ON acc_national_id_check
       FOR EACH ROW EXECUTE FUNCTION acc_national_id_check_rules();""",
]
