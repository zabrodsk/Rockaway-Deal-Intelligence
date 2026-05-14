import re
from pathlib import Path


def test_companies_sort_uses_latest_instead_of_alphabetical() -> None:
    html = (Path(__file__).resolve().parents[1] / "web" / "static" / "index.html").read_text()
    match = re.search(
        r'<select id="companies-sort-select" class="companies-sidebar-sort-select">(.*?)</select>',
        html,
        re.S,
    )

    assert match is not None
    companies_sort_html = match.group(1)
    assert '<option value="latest">LATEST</option>' in companies_sort_html
    assert '<option value="alphabetical">ALPHABETICAL</option>' not in companies_sort_html


def test_specter_url_mode_shows_deep_team_profiles_toggle() -> None:
    html = (Path(__file__).resolve().parents[1] / "web" / "static" / "index.html").read_text()

    assert 'id="fetch-full-team-toggle"' in html
    assert "Fetch deep team profiles (Specter)" in html
    assert "function syncUploadOptionToggles()" in html
    assert "const haveSpecterUrls = inputMode === 'specter' && specterUrls.length > 0;" in html
    assert "(inputMode === 'pitchdeck' || haveSpecterUrls) ? 'block' : 'none'" in html
    assert "syncUploadOptionToggles();\n    updateAnalyzeButtonState();" in html
    assert "fetch_full_team: fetchFullTeam" in html
