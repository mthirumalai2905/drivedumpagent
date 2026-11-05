from app.services.email_parser import parse_gmail_message
from tests.fakes import gmail_message


def test_parser_extracts_subject_body_and_attachment():
    message = gmail_message(
        "msg-1",
        "Back Office - November Invoice",
        "Please find the invoice attached.",
        [("invoice.pdf", "application/pdf", "att-1", 1200)],
    )
    parsed = parse_gmail_message(message)
    assert parsed.subject == "Back Office - November Invoice"
    assert "invoice attached" in parsed.body
    assert parsed.sender == "billing@example.com"
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].attachment_id == "att-1"
    assert parsed.attachments[0].filename == "invoice.pdf"


def test_parser_uses_html_when_plain_text_is_missing():
    message = gmail_message(
        "msg-2",
        "Back Office",
        "",
        [],
        html="<p>Please send this to the <b>back office</b>.</p>",
    )
    parsed = parse_gmail_message(message)
    assert "back office" in parsed.body
    assert "<b>" not in parsed.body
    assert parsed.attachments == []
