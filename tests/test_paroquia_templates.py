from pathlib import Path

PAROQUIA_TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "paroquia"


def test_paroquia_templates_top_banner_ad_absent():
    for template in PAROQUIA_TEMPLATES.glob("*.html"):
        html = template.read_text(encoding="utf-8")
        assert "highperformanceformat.com" not in html, template.name
        assert "atOptions" not in html, template.name
