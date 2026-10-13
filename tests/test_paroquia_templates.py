from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

AD_MARKERS = [
    "highperformanceformat.com",
    "effectivegatecpm.com",
    "atOptions",
    "googlesyndication.com",
    "adsbygoogle",
]


@pytest.mark.parametrize("template", sorted(TEMPLATES.rglob("*.html")), ids=lambda p: p.name)
def test_templates_ad_markup_absent(template):
    html = template.read_text(encoding="utf-8")
    for marker in AD_MARKERS:
        assert marker not in html, f"{marker} found in {template.name}"
