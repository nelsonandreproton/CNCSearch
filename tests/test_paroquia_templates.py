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


PUBLIC_TEMPLATES = sorted((TEMPLATES / "paroquia").glob("*.html"))
GA_IDS = [
    "G-E4DSXK4G1V",  # cânticos site property
    "G-C3BYBJW3Z0",  # main parish site property (www.paroquiacasaldecambra.pt)
]


@pytest.mark.parametrize("template", PUBLIC_TEMPLATES, ids=lambda p: p.name)
def test_public_templates_ga_configured_for_both_properties(template):
    html = template.read_text(encoding="utf-8")
    for ga_id in GA_IDS:
        assert f"gtag('config', '{ga_id}')" in html, f"{ga_id} not configured in {template.name}"
