"""Application security scanning stays apart from the container CI (operator, 2026-11-25)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
APPSEC = {
    "codeql.yml": "github/codeql-action/analyze@",  # SAST
    "dependency-review.yml": "actions/dependency-review-action@",  # SCA on pull requests
    "image-scan.yml": "aquasec/trivy:",  # SCA of the published images
    "dast.yml": "zaproxy/zaproxy:",  # DAST, a passive baseline
}


def test_each_scan_has_its_own_workflow_outside_the_container_ci() -> None:
    container_ci = (WORKFLOWS / "container-image.yml").read_text(encoding="utf-8")
    for name, marker in APPSEC.items():
        assert marker in (WORKFLOWS / name).read_text(encoding="utf-8"), name
        assert marker not in container_ci, name
    assert (ROOT / ".github" / "dependabot.yml").is_file()


def test_every_workflow_pins_actions_and_images_and_reads_no_secret() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert "secrets." not in text, path.name
        for line in text.splitlines():
            if "uses:" in line and "./" not in line:
                reference = line.split("uses:", 1)[1].split("#", 1)[0].strip()
                assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", reference), (path.name, line)
                assert re.search(r"# v\d", line), (path.name, line)
    for name in ("image-scan.yml", "dast.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        images = re.findall(r"_IMAGE: (\S+)", text)
        assert images and all(re.search(r"@sha256:[0-9a-f]{64}$", image) for image in images)


def test_dast_scans_behind_the_sign_in_on_a_throwaway_stack() -> None:
    """A side note (2026-11-26): the first ZAP runs saw only /, robots.txt and sitemap.xml,
    because ZAP could not sign in. The scan now signs in on the runner's throwaway stack, fails
    when it cannot, and scans the whole API from its OpenAPI document."""
    dast = (WORKFLOWS / "dast.yml").read_text(encoding="utf-8")
    for name in ("THOTH_AUTH_DEV_USERNAME", "THOTH_AUTH_DEV_PASSWORD", "THOTH_AUTH_DEV_EMAIL"):
        assert f'echo "{name}=' in dast
    assert "/auth/password" in dast and "/auth/me" in dast
    assert "ZAP_AUTH_HEADER_VALUE" in dast
    assert "zap-baseline.py" in dast and " -j " in dast  # the AJAX spider runs the SPA
    assert "zap-api-scan.py" in dast and "openapi.json" in dast
    assert "::add-mask::" in dast
    # Proven on the pull request that changes it, not only after a merge.
    assert ".github/workflows/dast.yml" in dast.split("jobs:", 1)[0]
