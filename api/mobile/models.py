"""MOB: server side of Tenmina Field for every field role (FR-MOB-001 to FR-MOB-012;
ADR-19, ADR-22; 02 sections 6.6 and 8.2 to 8.8)."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core import state
from core.models import BaseModel, CountryScopedModel

FIELD_ROLES = ("CT", "IN", "RN", "SV", "CE", "LW", "QS")
CHECKIN_SUBJECTS = ("care_visit", "property_inspection", "milestone_inspection", "errand_step")
FLAG_KINDS = ("outside_buffer", "time_gap", "before_previous_pass", "duplicate_hash", "metadata_mismatch",
              "bad_signature", "software_key", "outside_address_radius", "checkout_too_soon", "integrity_failed",
              "emulator", "unassigned_capture", "chain_break", "device_revoked", "hash_mismatch")


class Device(BaseModel):
    """A Tenmina Field install with its hardware-backed signing key (8.2)."""

    PLATFORMS = ("android", "ios")
    SECURITY = ("strongbox", "tee", "secure_enclave", "software")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="field_devices")
    platform = models.TextField(choices=[(p, p) for p in PLATFORMS])
    app_id = models.TextField()
    public_key = models.TextField()  # base64 DER SubjectPublicKeyInfo
    key_alg = models.TextField(choices=[("ES256", "ES256"), ("EdDSA", "EdDSA")], default="ES256")
    key_fingerprint = models.CharField(max_length=64, unique=True)  # SHA-256 of the key: one person per key
    key_security = models.TextField(choices=[(s, s) for s in SECURITY])
    attestation_kind = models.TextField(choices=[("android_key_attestation", "android_key_attestation"),
                                                 ("app_attest", "app_attest")])
    attestation = models.JSONField(default=dict, blank=True)  # chain or App Attest object as received
    app_attest_key_id = models.TextField(blank=True, default="")
    app_attest_counter = models.BigIntegerField(null=True, blank=True)
    integrity_verdict = models.JSONField(default=dict, blank=True)
    integrity_status = models.TextField(default="ok", choices=[("ok", "ok"), ("failed", "failed")])
    app_signing_digest = models.TextField(blank=True, default="")
    model = models.TextField(blank=True, default="")
    os_version = models.TextField(blank=True, default="")
    app_version = models.TextField(blank=True, default="")
    status = models.TextField(choices=[("active", "active"), ("revoked", "revoked")], default="active")
    registered_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    revoke_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "mob_device"
        constraints = [
            models.CheckConstraint(condition=~models.Q(key_security="secure_enclave") | models.Q(platform="ios"),
                                   name="mob_device_enclave_ios"),
            models.CheckConstraint(condition=~models.Q(key_security__in=["strongbox", "tee"])
                                   | models.Q(platform="android"), name="mob_device_keystore_android"),
            models.CheckConstraint(condition=(models.Q(attestation_kind="app_attest") & models.Q(platform="ios"))
                                   | (models.Q(attestation_kind="android_key_attestation")
                                      & models.Q(platform="android")), name="mob_device_attestation_kind"),
        ]


DEVICE = state.register("mob_device", "mob_device", {"active": {"revoked"}})


class DeviceChallenge(BaseModel):
    """One-time challenge for key attestation, Play Integrity or App Attest (8.2 step 1)."""

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    nonce = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mob_device_challenge"


class Assignment(CountryScopedModel):
    """Manual adapter for the field inbox: work staff assign directly. Line modules may
    register their own providers in mobile.inbox instead."""

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="field_assignments")
    subject_type = models.TextField()
    subject_id = models.UUIDField()
    kind = models.TextField(default="task")
    title = models.TextField()
    status = models.TextField(choices=[(s, s) for s in ("active", "revoked", "done")], default="active")
    address = models.TextField(blank=True, default="")
    point_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    point_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_m = models.PositiveIntegerField(null=True, blank=True)
    boundary = models.JSONField(default=list, blank=True)  # [[lat, lng], ...]
    buffer_m = models.PositiveIntegerField(null=True, blank=True)
    required_evidence = models.JSONField(default=list, blank=True)  # [{key, label, media, required}]
    checklist = models.JSONField(default=list, blank=True)  # [{key, label}]
    plan_items = models.JSONField(default=list, blank=True)
    previous_pass_at = models.DateTimeField(null=True, blank=True)
    project_key = models.TextField(blank=True, default="")
    accepts_submissions = models.BooleanField(default=True)
    state_reason = models.TextField(blank=True, default="")
    due_at = models.DateTimeField(null=True, blank=True)
    min_visit_minutes = models.PositiveIntegerField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mob_assignment"
        constraints = [models.UniqueConstraint(fields=["person", "subject_type", "subject_id"],
                                               condition=models.Q(status="active"), name="mob_assignment_active_uq")]


ASSIGNMENT = state.register("mob_assignment", "mob_assignment", {"active": {"revoked", "done"}})


class SyncCursor(BaseModel):
    """Opaque delta token for GET /v1/mobile/sync: what this device was last sent."""

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    device = models.ForeignKey(Device, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    keys = models.JSONField(default=list)
    digests = models.JSONField(default=dict)

    class Meta:
        db_table = "mob_sync_cursor"


class SignedManifest(CountryScopedModel):
    """A signed item from the device: evidence, check-in or check-out (8.4)."""

    KINDS = ("evidence", "checkin", "checkout")
    STATUS = ("registered", "uploaded", "stored", "rejected")
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="manifests")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    client_item_id = models.TextField()
    kind = models.TextField(choices=[(k, k) for k in KINDS], default="evidence")
    schema = models.TextField()
    manifest = models.JSONField()
    canonical_sha256 = models.CharField(max_length=64)
    item_sha256 = models.CharField(max_length=64, db_index=True)  # media hash, or the manifest's own hash
    signature = models.TextField()
    signature_alg = models.TextField()
    signature_valid = models.BooleanField()
    subject_type = models.TextField()
    subject_id = models.UUIDField()
    requirement_key = models.TextField(blank=True, default="")
    project_key = models.TextField(blank=True, default="")  # from the inbox item, for duplicate checks
    media_type = models.TextField(blank=True, default="")
    media_sha256 = models.CharField(max_length=64, blank=True, default="")
    media_size = models.BigIntegerField(null=True, blank=True)
    captured_at_device = models.DateTimeField()
    corrected_capture_at = models.DateTimeField()
    received_at = models.DateTimeField(default=timezone.now)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    accuracy_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    location_mock = models.BooleanField(default=False)
    previous_item_sha256 = models.CharField(max_length=64, blank=True, default="")
    app_version = models.TextField(blank=True, default="")
    status = models.TextField(choices=[(s, s) for s in STATUS], default="registered")
    reserved_evidence_id = models.UUIDField()
    evidence = models.OneToOneField("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="manifest")
    staged_key = models.TextField(blank=True, default="")
    unassigned_capture = models.BooleanField(default=False)
    rejection_reason = models.TextField(blank=True, default="")
    stored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mob_signed_manifest"
        constraints = [models.UniqueConstraint(fields=["person", "client_item_id"], name="mob_manifest_client_uq")]
        indexes = [models.Index(fields=["subject_type", "subject_id"])]


MANIFEST = state.register("mob_item", "mob_signed_manifest", {
    "registered": {"uploaded", "stored", "rejected"},
    "uploaded": {"stored", "rejected"},
})


class Submission(CountryScopedModel):
    """A milestone, task, visit or errand-step evidence set, or an inspection result (8.5 step 6)."""

    KINDS = ("evidence_set", "inspection")
    STATUS = ("received", "held_for_review", "cleared", "upheld")
    OUTCOMES = ("pass", "pass_with_defects", "fail")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    device = models.ForeignKey(Device, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    client_submission_id = models.TextField(unique=True)
    kind = models.TextField(choices=[(k, k) for k in KINDS], default="evidence_set")
    subject_type = models.TextField()
    subject_id = models.UUIDField()
    status = models.TextField(choices=[(s, s) for s in STATUS], default="received")
    outcome = models.TextField(blank=True, default="")
    checklist = models.JSONField(default=list, blank=True)
    defects = models.JSONField(default=list, blank=True)
    reason = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mob_submission"
        indexes = [models.Index(fields=["subject_type", "subject_id"])]
        constraints = [
            models.CheckConstraint(condition=models.Q(kind="evidence_set") | models.Q(outcome__in=["pass",
                                   "pass_with_defects", "fail"]), name="mob_inspection_has_outcome"),
            models.CheckConstraint(condition=~models.Q(outcome="fail") | ~models.Q(reason=""),
                                   name="mob_fail_has_reason"),
        ]


SUBMISSION = state.register("mob_submission", "mob_submission", {
    "received": {"held_for_review"},
    "held_for_review": {"cleared", "upheld"},
    "cleared": {"held_for_review"},
})


class SubmissionItem(BaseModel):
    submission = models.ForeignKey(Submission, on_delete=models.PROTECT, related_name="items")
    requirement_key = models.TextField()
    kind = models.TextField(choices=[(k, k) for k in ("evidence", "form", "defect_photo")], default="evidence")
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    manifest = models.ForeignKey(SignedManifest, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    value = models.JSONField(null=True, blank=True)  # tick, reading or defect value

    class Meta:
        db_table = "mob_submission_item"


class CheckIn(CountryScopedModel):
    """FR-MOB-012, RUL-23, ADR-19: signed check-in or check-out at a registered address."""

    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="+")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    subject_type = models.TextField(choices=[(s, s) for s in CHECKIN_SUBJECTS])
    subject_id = models.UUIDField()
    kind = models.TextField(choices=[("checkin", "checkin"), ("checkout", "checkout")])
    manifest = models.OneToOneField(SignedManifest, on_delete=models.PROTECT, related_name="checkin")
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.DecimalField(max_digits=8, decimal_places=2)
    registered_lat = models.DecimalField(max_digits=9, decimal_places=6)
    registered_lng = models.DecimalField(max_digits=9, decimal_places=6)
    distance_m = models.DecimalField(max_digits=10, decimal_places=2)
    radius_m = models.PositiveIntegerField()
    within_radius = models.BooleanField()
    device_time = models.DateTimeField()
    received_at = models.DateTimeField(default=timezone.now)
    signature_valid = models.BooleanField()
    checkin = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="checkout")
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "mob_checkin"
        constraints = [models.UniqueConstraint(fields=["subject_type", "subject_id", "kind"],
                                               name="mob_checkin_once")]


class FraudFlag(CountryScopedModel):
    """8.7 server checks. Flagged items reach a reviewer before an inspection is scheduled."""

    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="fraud_flags")
    manifest = models.ForeignKey(SignedManifest, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="flags")
    checkin = models.ForeignKey(CheckIn, null=True, blank=True, on_delete=models.PROTECT, related_name="flags")
    device = models.ForeignKey(Device, null=True, blank=True, on_delete=models.PROTECT, related_name="flags")
    subject_type = models.TextField(blank=True, default="")
    subject_id = models.UUIDField(null=True, blank=True)
    kind = models.TextField(choices=[(k, k) for k in FLAG_KINDS])
    detail = models.JSONField(default=dict)
    status = models.TextField(choices=[(s, s) for s in ("open", "cleared", "upheld")], default="open")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "mob_fraud_flag"
        indexes = [models.Index(fields=["status", "country"])]
        constraints = [models.CheckConstraint(condition=models.Q(evidence__isnull=False)
                                              | models.Q(manifest__isnull=False), name="mob_flag_has_item")]


FRAUD_FLAG = state.register("mob_fraud_flag", "mob_fraud_flag", {"open": {"cleared", "upheld"}})
