import io
import zipfile

from backend.services.content_reader import read_excerpt
from backend.services.file_classifier import classify_file, folder_for


def test_magic_bytes_override_a_misleading_name():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assert classify_file("invoice.pdf", "application/pdf", png) == "image"
    assert folder_for("image") == "Images"
    assert classify_file("scan.bin", "application/octet-stream", b"%PDF-1.7\n") == "pdf"
    assert folder_for("pdf") == "PDFs"


def test_office_zip_is_filed_and_its_text_can_be_read():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", "<a:t>Quarterly board report</a:t>")
    data = buffer.getvalue()
    assert classify_file("deck.bin", "application/octet-stream", data) == "presentation"
    assert folder_for("presentation") == "Presentations"
    assert "Quarterly board report" in read_excerpt(data, "presentation")


def test_video_bytes_and_names_go_to_videos():
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8
    assert classify_file("clip.bin", "application/octet-stream", mp4) == "video"
    assert folder_for("video") == "Videos"
    assert classify_file("talk.mp4", "video/mp4", b"not-a-container") == "video"
    assert classify_file("deck.pptx", "application/octet-stream", b"not-a-zip") == "presentation"


def test_csv_text_is_readable_and_unknown_files_stay_in_other():
    sheet = b"vendor,amount\nAcme Supplies,1200\n"
    assert classify_file("notes.csv", "text/csv", sheet) == "sheet"
    assert "Acme Supplies" in read_excerpt(sheet, "sheet")
    assert classify_file("payload.bin", "application/octet-stream", b"not-a-known-file") == "other"
    assert folder_for("other") == "Other"
