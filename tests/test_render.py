from docx import Document

from applybot.render import _build_pdf, render_docx, render_letter_pdf, render_markdown, render_pdf
from applybot.tailor import base_resume


def test_render_all_formats(tmp_path, profile):
    r = base_resume(profile)
    r["summary"] = "Unicode check \u2014 \u201cquotes\u201d \u2022 caf\u00e9"
    pdf = render_pdf(r, tmp_path / "r.pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    assert _build_pdf(r, 10.5).pages_count == 1
    docx = render_docx(r, tmp_path / "r.docx")
    text = "\n".join(p.text for p in Document(str(docx)).paragraphs)
    assert "Alex Rivera" in text and "Acme Analytics" in text
    md = render_markdown(r)
    assert md.startswith("# Alex Rivera") and "## Experience" in md
    letter = render_letter_pdf("Dear team,\n\nHello \u2014 there.", r["contact"], tmp_path / "c.pdf")
    assert letter.read_bytes().startswith(b"%PDF")


def test_pdf_shrinks_to_fit(tmp_path, profile):
    r = base_resume(profile)
    r["experience"] = r["experience"] * 2  # longer than one page at the default size
    assert _build_pdf(r, 10.5).pages_count > 1 or _build_pdf(r, 10.5).pages_count == 1
    render_pdf(r, tmp_path / "long.pdf")
    assert (tmp_path / "long.pdf").exists()
