"""Sample files for demo data (core.samples): real images and PDFs, marked SAMPLE, the same bytes every time,
small, accepted by the evidence store, and far enough apart for Tenmina Field's near-duplicate check."""
import io
import itertools

import pytest
from PIL import Image

from core import samples
from evidence.services import _image_meta, content_problem, phash_distance


@pytest.mark.parametrize("kind", samples.PHOTO_KINDS)
def test_every_photo_is_a_small_real_jpeg_and_the_same_each_time(kind):
    """FR-EVD-005: a real JPEG the store accepts, under 150 KB; deterministic for idempotent seeds."""
    data = samples.photo(kind, f"t-{kind}")
    assert data[:3] == b"\xff\xd8\xff" and len(data) < 150 * 1024
    assert content_problem(data, "image/jpeg") is None
    assert Image.open(io.BytesIO(data)).size == (samples.W, samples.H)
    assert samples._render(kind, f"t-{kind}", samples.DEFAULT_CAPTIONS[kind], None, "Samsung", None) == \
        samples._render(kind, f"t-{kind}", samples.DEFAULT_CAPTIONS[kind], None, "Samsung", None)


@pytest.mark.parametrize("kind", samples.PDF_KINDS)
def test_every_document_is_a_one_page_pdf_marked_sample(kind):
    """FR-EVD-005: no active content; the same bytes each time (fixed dates, no random identifier)."""
    data = samples.pdf(kind, f"t-{kind}", amount="100.00")
    assert data.startswith(b"%PDF-") and content_problem(data, "application/pdf") is None
    assert data == samples.pdf(kind, f"t-{kind}", amount="100.00")
    assert b"/Count 1" in data


def test_phone_exif_is_kept_for_field_checks():
    """The metadata check in Tenmina Field compares EXIF make and model with the registered phone."""
    meta, phash = _image_meta(samples.photo("foundation", "exif-test", model="SM-A045F"))
    assert meta["exif_model"] == "SM-A045F" and meta["exif_make"] == "Samsung" and phash


def test_photos_of_one_scene_are_not_near_duplicates():
    """mobile.fraud flags a capture within 4 bits of another project's photo; samples stay apart."""
    hashes = [_image_meta(samples.photo(k, f"dup-{n}"))[1] for k in ("land", "foundation", "house") for n in range(6)]
    assert all(phash_distance(a, b) > 4 for a, b in itertools.combinations(hashes, 2))


def test_file_for_picks_a_photo_or_a_document_from_the_name():
    data, ct, name = samples.file_for("TMC-1-site_photo", "image/jpeg")
    assert ct == "image/jpeg" and name.endswith(".jpg") and data[:3] == b"\xff\xd8\xff"
    data, ct, name = samples.file_for("receipt-KATH-0120.txt")
    assert ct == "application/pdf" and name == "receipt-KATH-0120.pdf" and data.startswith(b"%PDF-")
    assert samples.doc_kind_for("site-plan-east-legon") == "site_plan"
    assert samples.doc_kind_for("ghana_card") == "id" and samples.photo_kind_for("room_kitchen") == "room_kitchen"
