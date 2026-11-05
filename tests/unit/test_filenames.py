from backend.services.attachment_processor import sanitize_filename, validate_attachment


ALLOW = {"application/pdf", "text/plain"}


def test_path_traversal_is_reduced_to_the_basename():
    assert sanitize_filename("../../secret.pdf") == "secret.pdf"
    assert sanitize_filename("..\\..\\secret.pdf") == "secret.pdf"


def test_null_byte_is_removed():
    assert sanitize_filename("invoice.pdf\x00.exe") == "invoice.pdf.exe"


def test_empty_name_becomes_attachment():
    assert sanitize_filename("   ") == "attachment"
    assert sanitize_filename("..") == "attachment"


def test_mime_and_size_rules():
    ok = validate_attachment(
        filename="invoice.pdf",
        mime_type="application/pdf",
        size=100,
        allowed_mimes=ALLOW,
        max_bytes=1000,
    )
    assert ok.ok is True
    blocked = validate_attachment(
        filename="run.exe",
        mime_type="application/x-msdownload",
        size=100,
        allowed_mimes=ALLOW,
        max_bytes=1000,
    )
    assert blocked.ok is False
    assert blocked.reason == "mime type is not allowed"
    oversized = validate_attachment(
        filename="invoice.pdf",
        mime_type="application/pdf",
        size=5000,
        allowed_mimes=ALLOW,
        max_bytes=1000,
    )
    assert oversized.reason == "attachment exceeds size limit"
