"""PDF z HTML (WeasyPrint) — dokumenty z tabel i tekstu, np. sprawozdania wtyczek.

Domyślnie PDF/A-2b: czcionki osadzone, profil kolorów sRGB, metadane XMP — postać zalecana do archiwizacji
i do podpisu elektronicznego (PAdES, podpis kwalifikowany w EZD). Układ strony, nagłówki, stopki
i numeracja stron — w CSS (`@page`, `counter(page)`, `counter(pages)`); nagłówek tabeli (`<thead>`)
powtarza się na każdej stronie. Obrazy najlepiej osadzać jako `data:` URI (bez pobierania z sieci).

Generowanie trwa od ułamka sekundy do kilku sekund — wołaj w wątku (`asyncio.to_thread`).
"""
from __future__ import annotations

PDF_VARIANT = "pdf/a-2b"
# PDF/A (ISO 19005-2, 6.2.8) zabrania wygładzania obrazów (/Interpolate true), które WeasyPrint ustawia przy
# `image-rendering: auto` — wymuszamy wyłączenie dla wszystkich obrazów dokumentu (sprawdzone veraPDF).
PDFA_CSS = "* { image-rendering: crisp-edges !important; }"


def html_to_pdf(html: str, *, title: str | None = None, author: str | None = None, pdfa: bool = True) -> bytes:
    """Dokument HTML (z własnym CSS) → PDF (domyślnie PDF/A-2b). Tytuł i autor trafiają do metadanych."""
    from weasyprint import CSS, HTML
    from weasyprint.urls import URLFetcher

    # bez sieci i plików: dokument ma mieć wszystko w sobie (obrazy jako data: URI)
    doc = HTML(string=html, url_fetcher=URLFetcher(allowed_protocols={"data"}), base_url="about:blank").render(
        stylesheets=[CSS(string=PDFA_CSS)] if pdfa else None)
    if title:
        doc.metadata.title = title
    if author:
        doc.metadata.authors = [author]
    return doc.write_pdf(pdf_variant=PDF_VARIANT if pdfa else None)
