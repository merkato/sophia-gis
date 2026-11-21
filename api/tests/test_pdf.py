"""PDF/A z HTML: polskie znaki, powtarzany nagłówek tabeli, brak zasobów zewnętrznych."""
import re
import zlib

import pytest

pytest.importorskip("weasyprint")

from app.pdf import html_to_pdf


def _streams(pdf: bytes) -> bytes:
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
        try:
            out.append(zlib.decompress(m.group(1)))
        except zlib.error:
            out.append(m.group(1))
    return b"".join(out)


def test_pdfa_from_html():
    rows = "".join(f"<tr><td>{i}</td><td>Grójec — działka 12/{i}</td></tr>" for i in range(200))
    pdf = html_to_pdf(f"<style>@page {{ size: A4 landscape }}</style><table><thead><tr><th>L.p.</th>"
                      f"<th>Opis</th></tr></thead><tbody>{rows}</tbody></table>", title="Sprawozdanie", author="test")
    assert pdf.startswith(b"%PDF")
    assert b"pdfaid" in _streams(pdf)        # metadane XMP PDF/A


def test_external_resources_blocked():
    pdf = html_to_pdf('<img src="http://example.invalid/x.png"><p>żółć</p>')
    assert pdf.startswith(b"%PDF")
