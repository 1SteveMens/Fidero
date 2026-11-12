"""Seeded people for development. Password for all: tenmina-dev-123.
MFA secret for staff is fixed so tests and demos can compute codes."""
from .models import Organisation, Person, RoleGrant

DEV_PASSWORD = "tenmina-dev-123"
DEV_MFA_SECRET = "JBSWY3DPEHPK3PXP"

PEOPLE = [
    ("client", "ama@example.com", "Ama Mensah", ["CL"], "GB"),
    ("client2", "kofi@example.com", "Kofi Boateng", ["CL"], "US"),
    ("cm", "cm@tenmina.test", "Esi Case Manager", ["CM"], "GH"),
    ("reviewer", "rv1@tenmina.test", "Yaw Reviewer", ["RV", "RR", "PY"], "GH"),
    ("reviewer2", "rv2@tenmina.test", "Akosua Reviewer", ["RV", "RR", "PY"], "GH"),
    ("admin", "admin@tenmina.test", "Kwame Admin", ["AD", "RR", "PY"], "GH"),
    ("admin2", "admin2@tenmina.test", "Abena Admin", ["AD", "RR", "PY"], "GH"),
    ("lawyer", "lawyer@example.com", "Nana Lawyer", ["LW"], "GH"),
    ("surveyor", "surveyor@example.com", "Kojo Surveyor", ["SV"], "GH"),
    ("runner", "runner@example.com", "Efua Runner", ["RN"], "GH"),
    ("inspector", "inspector@example.com", "Kwesi Inspector", ["IN"], "GH"),
    ("qs", "qs@example.com", "Adjoa Quantity Surveyor", ["QS"], "GH"),
    ("carer", "carer@example.com", "Afia Carer", ["CE"], "GH"),
    ("agent", "agent@example.com", "Yaa Errand Agent", ["CE"], "GH"),
    ("seller", "seller@example.com", "Ato Estates Ltd", ["SE"], "GH"),
    ("contractor", "builder@example.com", "Kobby Builders", ["CT"], "GH"),
    ("family", "auntie@example.com", "Auntie Comfort", ["FM"], "GH"),
    ("institution", "bursar@example.com", "School Bursar", ["IC"], "GH"),
    ("partner", "partner@example.com", "Partner Bank API", ["PT"], "GH"),
    ("insurer", "insurer@example.com", "Insurer Partner", ["IS"], "GH"),
    ("tenant", "tenant@example.com", "Tenant Kwabena", ["TN"], "GH"),
    ("developer", "dev@example.com", "Off-plan Developer", ["DV"], "GH"),
    ("authority", "stool@example.com", "Stool Secretary", ["AR"], "GH"),
]


def run(ctx):
    gh = ctx["gh"]
    for key, email, name, roles, residence in PEOPLE:
        p = Person.objects.filter(email=email).first()
        if not p:
            p = Person.objects.create_user(email, DEV_PASSWORD, full_name=name, home_country=gh,
                                           residence_country=residence)
            for r in roles:
                RoleGrant.objects.create(person=p, role=r)
            if any(r in ("CM", "RV", "AD") for r in roles):
                p.mfa_secret, p.mfa_enabled = DEV_MFA_SECRET, True
                p.save(update_fields=["mfa_secret", "mfa_enabled"])
        ctx["people"][key] = p
    admin = ctx["people"]["admin"]
    if not admin.is_superuser:
        admin.is_staff = admin.is_superuser = True
        admin.save(update_fields=["is_staff", "is_superuser"])
    for name, kind in [("Ato Estates Ltd", "seller"), ("Kobby Builders", "contractor"),
                       ("Tenmina Partner Bank [TO VERIFY]", "bank")]:
        Organisation.objects.get_or_create(name=name, kind=kind, country=gh)
