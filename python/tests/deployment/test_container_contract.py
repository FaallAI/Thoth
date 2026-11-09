import json
import re
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _repo_text(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_dockerignore_excludes_sensitive_and_generated_inputs() -> None:
    patterns = {
        line.strip()
        for line in _repo_text(".dockerignore").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_patterns = {
        ".git",
        ".worktrees",
        ".agents",
        ".claude",
        ".codex",
        ".superpowers",
        "**/.env*",
        "data/cookies.txt",
        "**/*.key",
        "**/node_modules",
        "python/.venv",
        "**/__pycache__",
        "**/.pytest_cache",
        "**/.ruff_cache",
        "**/target",
        "output",
        "scout/output",
        ".thoth-artifacts",
        "*.db*",
        "*.log",
        "*.mp4",
        "*.wav",
        "*.jpg",
        "**/*.png",
        "**/*.part",
        "tiktok-stage1-soak-observations*.jsonl",
        "tiktok-stage1-soak-report.json*",
    }
    assert required_patterns <= patterns
    # The tracked release capsule is media the parity image has to render, and
    # narration seeds the bundled SFX from the image (spec 2026-10-31); the rules
    # above would otherwise drop both.
    negations = {pattern for pattern in patterns if pattern.startswith("!")}
    assert negations == {
        "!packages/remotion-composition/releases/**",
        "!assets/sfx/**",
        "!assets/asset_catalog.json",
    }


def test_dockerfile_uses_locked_full_compatibility_runtime() -> None:
    dockerfile = _repo_text("Dockerfile")
    assert "FROM ghcr.io/astral-sh/uv:0.13.5 AS uv-tools" in dockerfile
    assert "FROM oven/bun:1.4.4 AS bun-tools" in dockerfile
    assert "FROM python:3.12-slim-bookworm AS runtime" in dockerfile
    assert "uv sync --frozen --no-dev --extra acquisition" in dockerfile
    assert "/opt/thoth/python/.venv/bin/patchright install --with-deps chromium" in dockerfile
    # The image carries exactly one Chromium and it is patchright's — the stealthy sessions
    # launch through patchright, which pins its own revision. The 2026-10-23 refresh shipped
    # the driver without its browser and every card visit failed as headless_blocked.
    assert "/opt/thoth/python/.venv/bin/scrapling install" not in dockerfile
    assert "COPY . " not in dockerfile


def test_the_stealthy_browser_launch_smoke_gates_publication_and_deploy() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    validation = workflow.split("  validate-image:", 1)[1].split("  publish-image:", 1)[0]
    assert "test-browser-offline.sh" in validation
    assert "test-browser-offline.sh" in _repo_text("scripts/ops/deploy-stage1.sh")


def test_dockerfile_keeps_a_non_root_runtime() -> None:
    dockerfile = _repo_text("Dockerfile")
    assert "THOTH_CONTROL_PLANE_ARTIFACT_ROOT=/var/lib/thoth/artifacts" in dockerfile
    assert "USER thoth" in dockerfile
    assert "RUN test -w /var/lib/thoth/artifacts" in dockerfile


def test_dockerfile_default_command_is_worker_and_has_no_secret_arguments() -> None:
    dockerfile = _repo_text("Dockerfile")
    assert (
        'CMD ["/opt/thoth/python/.venv/bin/python", "-m", '
        '"thoth_control_plane.worker"]' in dockerfile
    )
    assert "THOTH_LIVE_TIKTOK_URL" not in dockerfile
    assert "THOTH_CONTROL_PLANE_API_KEY=" not in dockerfile
    assert "ARG THOTH_" not in dockerfile


def test_container_workflow_separates_pr_validation_from_publication() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    validation = workflow.split("  validate-image:", 1)[1].split("  publish-image:", 1)[0]
    publication = workflow.split("  publish-image:", 1)[1]
    assert "if: github.event_name == 'pull_request'" in validation
    assert "push: false" in validation
    assert "packages: write" not in validation
    assert "if: github.event_name == 'push'" in publication
    assert "packages: write" in publication
    assert "push: true" in publication
    assert workflow.count("packages: write") == 1


def test_container_workflow_boots_the_stack_it_publishes() -> None:
    """Rendering Compose cannot open a path that lives inside the image.

    `docker compose config` resolved a dynamic-config path that did not exist in the
    pinned Temporal image, so the offline gate passed while the stack crash-looped.
    Publication is therefore also gated on the four non-live services reporting
    healthy against the digest that was just published.
    """
    workflow = _repo_text(".github/workflows/container-image.yml")
    assert "  stack-smoke:" in workflow
    smoke = workflow.split("  stack-smoke:", 1)[1]
    assert "needs: publish-image" in smoke
    assert "up -d --wait postgresql editor-postgresql temporal temporal-ui api" in smoke
    assert "exec -T api id -u" in smoke
    assert "test -w /var/lib/thoth/artifacts" in smoke
    assert "operator namespace describe" in smoke
    assert "stage1-local-preflight" in smoke


def test_container_workflow_smoke_never_starts_the_live_services() -> None:
    """The worker acquires from live platforms; CI never starts it."""
    workflow = _repo_text(".github/workflows/container-image.yml")
    smoke = workflow.split("  stack-smoke:", 1)[1]
    assert " worker" not in smoke.replace("--wait postgresql temporal temporal-ui api", "")
    assert "down -v" not in smoke


def test_container_workflow_pins_gates_tags_platform_and_digest_summary() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    assert "REGISTRY_IMAGE: ghcr.io/faallai/thoth" in workflow
    # From python/, so pytest reads python/pyproject.toml (asyncio_mode and markers).
    assert (
        "working-directory: python\n"
        "        env:\n"
        "          THOTH_TEST_WHISPER_MODEL_DIR: ${{ runner.temp }}/models/whisper-tiny\n"
        "          THOTH_TEST_DIARIZATION_MODEL_DIR: ${{ runner.temp }}/models/diarization\n"
        "          THOTH_TEST_EMBEDDING_MODEL_DIR: ${{ runner.temp }}/models/embedding\n"
        "          THOTH_TEST_EDITOR_DATABASE_URL: postgresql://postgres:thoth@127.0.0.1:5432/postgres\n"
        '          THOTH_REQUIRE_POSTGRES_TESTS: "1"\n'
        "          THOTH_TEST_MEDIA_S3_ENDPOINT: 127.0.0.1:9000\n"
        "          THOTH_TEST_MEDIA_S3_ACCESS_KEY: thoth-test\n"
        "          THOTH_TEST_MEDIA_S3_SECRET_KEY: thoth-test-secret\n"
        '          THOTH_REQUIRE_MINIO_TESTS: "1"\n'
        '          THOTH_REQUIRE_BROWSER_TESTS: "1"\n'
        '        run: uv run pytest -m "not live" -q'
    ) in workflow
    # The card selectors are checked against recorded pages in Chromium (spec 5c-2); without a
    # browser those tests would skip and a broken selector would pass CI unseen.
    assert "uv run playwright install --with-deps chromium" in workflow
    # The speech adapter tests fail without models (operator, 2026-10-13), so CI fetches them.
    assert "fetch_speech_models.py --whisper tiny" in workflow
    assert "platforms: linux/amd64" in workflow
    assert "type=raw,value=sha-${{ github.sha }}" in workflow
    assert "type=ref,event=branch" in workflow
    assert "type=ref,event=tag" in workflow
    assert "refs/heads/master" in workflow
    assert "provenance: mode=max" in workflow
    assert "sbom: true" in workflow
    assert "steps.build.outputs.digest" in workflow
    assert "secrets." not in workflow


#: The renderer is a second image from a second Dockerfile, so it gets a second
#: repository. One repository holding two unrelated runtimes would make a digest
#: ambiguous about which one it names.
RENDERER_REGISTRY = "ghcr.io/faallai/thoth-remotion-renderer"


def test_container_workflow_publishes_the_renderer_as_its_own_image() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    publication = workflow.split("  publish-image:", 1)[1].split("  stack-smoke:", 1)[0]

    assert f"RENDERER_REGISTRY_IMAGE: {RENDERER_REGISTRY}" in workflow
    # The existing application image keeps its repository and its identity.
    assert "REGISTRY_IMAGE: ghcr.io/faallai/thoth\n" in workflow
    assert "file: Dockerfile.renderer" in publication
    assert "images: ${{ env.RENDERER_REGISTRY_IMAGE }}" in publication
    assert "org.opencontainers.image.revision=${{ github.sha }}" in publication
    # The dashboard web image (spec 2026-10-19) is the third published image.
    assert "file: Dockerfile.web" in publication
    assert "images: ${{ env.WEB_REGISTRY_IMAGE }}" in publication
    assert publication.count("push: true") == 3
    assert publication.count("provenance: mode=max") == 3
    assert publication.count("sbom: true") == 3


def test_container_workflow_exposes_each_published_digest_separately() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    outputs = workflow.split("    outputs:\n", 1)[1].split("    steps:", 1)[0]

    assert "digest: ${{ steps.build.outputs.digest }}" in outputs
    assert "renderer_digest: ${{ steps.renderer-build.outputs.digest }}" in outputs
    assert "web_digest: ${{ steps.web-build.outputs.digest }}" in outputs
    summary = workflow.split("Record immutable release identity", 1)[1]
    assert "RENDERER_IMAGE_DIGEST: ${{ steps.renderer-build.outputs.digest }}" in summary
    assert "${RENDERER_REGISTRY_IMAGE}" in summary


def test_container_workflow_validates_both_candidate_images_without_publishing() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    validation = workflow.split("  validate-image:", 1)[1].split("  publish-image:", 1)[0]

    assert "RENDERER_CANDIDATE_IMAGE: thoth-remotion-renderer:pr-${{ github.sha }}" in validation
    assert "file: Dockerfile.renderer" in validation
    assert "WEB_CANDIDATE_IMAGE: thoth-web:pr-${{ github.sha }}" in validation
    assert "file: Dockerfile.web" in validation
    assert validation.count("push: false") == 3
    assert validation.count("load: true") == 3
    assert "packages: write" not in validation
    assert (
        'bash docker/test-renderer-offline.sh "${CANDIDATE_IMAGE}" '
        '"${RENDERER_CANDIDATE_IMAGE}"' in validation
    )


def test_container_workflow_smokes_the_render_stack_on_published_digests() -> None:
    """A published pair is the only identity a deployment can actually pull."""
    workflow = _repo_text(".github/workflows/container-image.yml")
    smoke = workflow.split("  stack-smoke:", 1)[1]

    assert (
        "THOTH_RENDERER_IMAGE_REF: "
        f"{RENDERER_REGISTRY}@${{{{ needs.publish-image.outputs.renderer_digest }}}}" in smoke
    )
    assert (
        'bash docker/test-renderer-offline.sh "${THOTH_IMAGE_REF}" '
        '"${THOTH_RENDERER_IMAGE_REF}"' in smoke
    )
    # The harness builds its own two-image stack from these arguments, and the
    # shared stack no longer starts a renderer, so the throwaway environment
    # carries no renderer input for a service this job never runs.
    assert 'echo "THOTH_RENDERER_IMAGE=' not in smoke
    assert 'echo "THOTH_RENDERER_INTERNAL_CREDENTIAL=' not in smoke


def test_container_workflow_never_prints_a_generated_credential() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    generated = [line for line in workflow.splitlines() if "openssl rand" in line]

    assert generated
    for line in generated:
        # Every generated value goes straight into the ignored throwaway file.
        assert line.strip().startswith('echo "THOTH_')
    assert "> stage1.ci.env" in workflow
    assert "cat stage1.ci.env" not in workflow


def test_renderer_smoke_is_a_two_image_self_cleaning_harness() -> None:
    """The harness owns exactly what it created and nothing that was already there."""
    script = _repo_text("docker/test-renderer-offline.sh")

    assert "set -euo pipefail" in script
    assert "umask 077" in script
    assert "usage: docker/test-renderer-offline.sh IMAGE RENDERER_IMAGE WEB_IMAGE" in script
    assert '[ "$#" -ne 3 ]' in script
    assert "mktemp -d" in script
    assert "trap teardown EXIT INT TERM" in script
    # Broad cleanup would take the operator's own stack with it.
    assert "system prune" not in script
    assert "docker rm -f" not in script
    assert "docker network prune" not in script
    assert "docker volume prune" not in script
    assert "down -v" not in script


def test_renderer_smoke_proves_the_properties_a_render_stack_must_hold() -> None:
    script = _repo_text("docker/test-renderer-offline.sh")
    required = {
        "api_healthz_ready=true",
        "api_readyz_ready=true",
        "renderer_runs_unprivileged=true",
        "renderer_host_binding_absent=true",
        "renderer_holds_no_control_plane_capability=true",
        "render_output_is_h264_mp4=true",
        "render_output_checksum_matches=true",
        "render_output_in_the_store=true",
        "second_render_is_refused=true",
        "no_waiting_row_was_created=true",
        "cancel_leaves_no_published_output=true",
        "deadline_fails_without_publishing=true",
        "teardown_leaves_nothing=true",
        "workflow_opens_in_studio=true",
    }
    assert required <= set(script.split())


def test_renderer_smoke_waits_for_readiness_and_not_only_liveness() -> None:
    """``/healthz`` answers before the workflow gateway exists.

    The harness runs a throwaway Temporal precisely because ``/readyz`` proves
    it, so a broken backend or namespace has to fail the smoke instead of
    passing an unconditional liveness probe.
    """
    script = _repo_text("docker/test-renderer-offline.sh")

    assert "urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200" in script
    assert "urlopen('http://127.0.0.1:8000/readyz', timeout=2).status == 200" in script
    assert "|| fail api_healthz_ready" in script
    assert "|| fail api_readyz_ready" in script


def test_renderer_smoke_accepts_only_the_deadline_failure_code() -> None:
    """Any terminal failure used to satisfy the deadline phase.

    A bundle, engine, dispatch, or output failure also ends ``failed`` and also
    publishes nothing, so the verdict would have held for a defect that has
    nothing to do with the deadline. It now names the one code the deadline
    itself produces, and prints the observed code either way.
    """
    script = _repo_text("docker/test-renderer-offline.sh")

    assert 'code=$(driver failure "$deadline_job")' in script
    assert 'echo "deadline_failure_code=${code}"' in script
    assert '[ "$code" = "render_deadline_exceeded" ] || fail deadline_fails_without_publishing' in (
        script
    )
    for unrelated in ("render_engine_failed", "render_bundle_invalid", "render_output_invalid"):
        assert unrelated not in script


def test_renderer_smoke_reads_no_real_credential_or_asset() -> None:
    script = _repo_text("docker/test-renderer-offline.sh")

    assert ".env.stage1" not in script
    assert "compose.stage1" not in script
    assert "tiktok.com" not in script
    assert "ghcr.io" not in script
    assert "THOTH_STAGE1_DATA_ROOT" not in script
    assert "openssl rand" in script


def test_quality_workflow_provisions_linux_ffmpeg_for_the_media_tests() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    assert "Install media test dependencies" in workflow
    assert "sudo apt-get update" in workflow
    assert "sudo apt-get install --yes --no-install-recommends ffmpeg" in workflow
    assert "THOTH_FFMPEG: /usr/bin/ffmpeg" in workflow
    assert "THOTH_FFPROBE: /usr/bin/ffprobe" in workflow
    assert 'test -x "$THOTH_FFMPEG"' in workflow
    assert 'test -x "$THOTH_FFPROBE"' in workflow


def test_operations_documentation_requires_digest_pinning_and_runtime_injection() -> None:
    documentation = _repo_text("docs/python-control-plane.md")
    digest_prompt = 'Read-Host "Paste the sha256 digest from the successful workflow summary"'
    assert "### Stage 1 compatibility container" in documentation
    assert "ghcr.io/faallai/thoth@" in documentation
    assert digest_prompt in documentation
    assert "/var/lib/thoth/artifacts" in documentation
    assert "thoth_control_plane.api.app:create_app" in documentation
    assert "Publishing the image does not deploy it to AWS" in documentation


def test_dockerfile_pins_base_interpreter_and_editable_layout() -> None:
    """The spec's runtime line and editable layout must be enforced by the build itself.

    `uv` prefers its own managed interpreters by default, so an unpinned `uv sync`
    can resolve a downloaded CPython under `/root` instead of the base image's
    3.12. That would both violate the `python:3.12-slim-bookworm` runtime line and
    leave `.venv/bin/python` unreadable after dropping to `thoth`.
    """
    dockerfile = _repo_text("Dockerfile")
    assert "UV_PYTHON=/usr/local/bin/python3.12" in dockerfile
    assert "UV_PYTHON_DOWNLOADS=never" in dockerfile
    assert "assert sys.version_info[:2] == (3, 12), sys.version" in dockerfile
    assert "assert m.__file__.startswith('/opt/thoth/python/src/'), m.__file__" in dockerfile


def test_dockerfile_provides_linux_media_runtime() -> None:
    dockerfile = _repo_text("Dockerfile")
    assert "ca-certificates ffmpeg tini" in dockerfile
    assert "THOTH_FFMPEG=/usr/bin/ffmpeg" in dockerfile
    assert "THOTH_FFPROBE=/usr/bin/ffprobe" in dockerfile
    assert "/usr/bin/ffmpeg -version" in dockerfile
    assert "/usr/bin/ffprobe -version" in dockerfile
    assert "EXPOSE 8000\n" in dockerfile


def test_container_workflow_pins_every_action_to_full_commit_sha() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    expected = {
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1": "# v7.0.1",
        "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0": "# v7.1.0",
        "astral-sh/setup-uv@07a047e608db84b3d8c06cd9a7c7dcc9c355c18e": "# v10.3.2",
        "oven-sh/setup-bun@0c5077e51419868618aeaa5fe8019c62421857d6": "# v2.2.0",
        "docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069": "# v4.4.1",
        "docker/login-action@dbcb813823bdd20940b903addbd779551569679f": "# v4.6.0",
        "docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302": "# v6.2.0",
        "docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc": "# v7.4.0",
    }
    action_lines = [line for line in workflow.splitlines() if "uses:" in line]
    references = {
        line.split("uses:", 1)[1].split("#", 1)[0].strip()
        for line in action_lines
        if not line.split("uses:", 1)[1].strip().startswith("./")
    }
    assert references == set(expected)
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", reference) for reference in references)
    for line in action_lines:
        reference = line.split("uses:", 1)[1].split("#", 1)[0].strip()
        if reference in expected:
            assert line.rstrip().endswith(expected[reference])


def test_blueprint_records_published_container_checkpoint() -> None:
    blueprint = _repo_text("BLUEPRINT.md")
    prose = " ".join(blueprint.split())
    assert "Stage 1 container checkpoint (2026-09-04)" in blueprint
    assert "worker/API/CDP sidecar" in blueprint
    assert "Deployment, controlled live smoke, and the operational soak remain pending" in prose
    assert "| Stage 1 container + CI | ⚠️ 95% |" in blueprint
    assert "`Dockerfile`, `.github/workflows/container-image.yml`" in blueprint


def test_blueprint_does_not_pin_a_release_digest_it_cannot_keep_current() -> None:
    """Every push publishes a new digest, so a digest written here is stale on arrival.

    The image labels bind each digest to its own revision, which means the commit that
    records a digest can never be the commit that digest was built from. The blueprint
    therefore names the source of the release identity instead of a literal digest.
    """
    blueprint = _repo_text("BLUEPRINT.md")
    prose = " ".join(blueprint.split())
    assert not re.search(r"ghcr\.io/faallai/thoth@sha256:[0-9a-f]{64}", blueprint)
    assert "read from the Actions summary of the exact commit being deployed" in prose


def _yt_dlp_pin() -> str:
    """The single yt-dlp pin; the yt-dlp update workflow bumps it and the lock only."""
    (pin,) = set(re.findall(r'"yt-dlp==([0-9.]+)"', _repo_text("python/pyproject.toml")))
    return pin


def test_uv_lock_resolves_the_pinned_downloader() -> None:
    lock = tomllib.loads(_repo_text("python/uv.lock"))
    locked = {package["name"]: package["version"] for package in lock["package"]}
    assert "gallery-dl" not in locked  # Scout's image downloader, retired with it
    assert locked["yt-dlp"] == _yt_dlp_pin()


def test_dockerfile_syncs_the_acquisition_extra_in_every_locked_install() -> None:
    dockerfile = _repo_text("Dockerfile")
    sync_commands = [line.strip() for line in dockerfile.splitlines() if "uv sync --frozen" in line]
    assert len(sync_commands) == 2
    assert all("--extra acquisition" in command for command in sync_commands)
    assert not any("scout-runtime" in command for command in sync_commands)


def test_dockerfile_probes_downloader_executables_as_the_runtime_user() -> None:
    """A source-level pin proves nothing about the layer the worker actually runs.

    The probes live after `USER thoth` so the build fails when the executables are
    missing, unreadable by the runtime user, or a different version than the lock.
    """
    dockerfile = _repo_text("Dockerfile")
    runtime_stage = dockerfile.split("USER thoth", 1)[1]
    assert "YTDLP=/opt/thoth/python/.venv/bin/yt-dlp" in dockerfile
    assert 'test -x "$YTDLP"' in runtime_stage
    # yt-dlp prints `2026.08.19` where the lock says `2026.8.19`; the probe compares the
    # executable with the package the frozen sync installed, so a bump needs no edit here.
    ytdlp_probe = (
        '&& test "$("$YTDLP" --version | sed -E \'s/(^|\\.)0+([0-9])/\\1\\2/g\')" = '
        "\"$(/opt/thoth/python/.venv/bin/python -c 'import importlib.metadata as m; "
        'print(m.version("yt-dlp"))\')" \\'
    )
    assert ytdlp_probe in runtime_stage
    assert not re.search(r'"\d{4}\.\d{2}\.\d{2}"', runtime_stage)


def test_pull_request_builds_load_the_image_and_prove_the_browser_launches() -> None:
    """A PR must fail on a browser that cannot start, which requires the image locally.

    `push: false` alone leaves the build in the buildx cache with nothing to run, so
    the regression the launch smoke exists to catch would pass review.
    """
    workflow = _repo_text(".github/workflows/container-image.yml")
    validate = workflow[workflow.index("  validate-image:") : workflow.index("  publish-image:")]

    assert "push: false" in validate
    assert "load: true" in validate
    assert "tags: ${{ env.CANDIDATE_IMAGE }}" in validate
    assert 'bash docker/test-browser-offline.sh "${CANDIDATE_IMAGE}"' in validate
    assert "compose.stage1.local.yml" not in validate


def test_published_digest_is_proved_by_the_same_harness() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")
    smoke = workflow[workflow.index("  stack-smoke:") :]

    assert (
        "THOTH_IMAGE_REF: ghcr.io/faallai/thoth@${{ needs.publish-image.outputs.digest }}" in smoke
    )
    assert 'bash docker/test-renderer-offline.sh "${THOTH_IMAGE_REF}"' in smoke
    assert "up -d --wait postgresql editor-postgresql temporal temporal-ui api" in smoke
    assert "curl -fsS http://127.0.0.1:8000/readyz" in smoke


def test_the_image_and_its_workflow_carry_no_scout() -> None:
    """Scout and its CDP sidecar are retired (operator, 2026-10-30); none of it ships."""
    dockerfile = _repo_text("Dockerfile")
    workflow = _repo_text(".github/workflows/container-image.yml")
    for retired in ("scout", "cdp", "18800", "gallery", "browser-profile"):
        assert retired not in dockerfile.lower()
        assert retired not in workflow.lower()
    assert not (REPOSITORY_ROOT / "scout").exists()
    assert not (REPOSITORY_ROOT / "docker/start-legacy-cdp").exists()


def test_editor_preview_signing_key_is_injected_at_runtime_only() -> None:
    """The signing key is an operator input, so the image must never carry one."""
    dockerfile = _repo_text("Dockerfile")
    assert "THOTH_EDITOR_PREVIEW_SIGNING_KEY" not in dockerfile

    workflow = _repo_text(".github/workflows/container-image.yml")
    smoke = workflow.split("  stack-smoke:", 1)[1]
    assert 'echo "THOTH_EDITOR_PREVIEW_SIGNING_KEY=$(openssl rand -hex 24)"' in smoke
    # Generated into the throwaway env file, never echoed as an output or a summary.
    assert "THOTH_EDITOR_PREVIEW_SIGNING_KEY" not in smoke.split("> stage1.ci.env", 1)[1]


def test_renderer_image_carries_the_composition_without_the_release_capsule() -> None:
    dockerfile = _repo_text("Dockerfile.renderer")
    copied = [line for line in dockerfile.splitlines() if line.startswith("COPY")]

    assert any(
        "packages/remotion-composition/src/ /opt/thoth/packages/remotion-composition/src/" in line
        for line in copied
    )
    # The whole package would drag the release capsule into the service image.
    whole = "packages/remotion-composition/ /opt/thoth/packages/remotion-composition/"
    assert not any(line.rstrip().endswith(whole) for line in copied)
    assert not any("releases" in line for line in copied)
    # The parity page and its harness are development surfaces. They are kept out
    # of the layer rather than deleted from it, so no layer ever carried them.
    assert "--exclude=release-capture.tsx --exclude=release-preview-entry.tsx" in dockerfile
    assert "test ! -e /opt/thoth/renderer/src/release-preview-entry.tsx" in dockerfile
    assert "test ! -d /opt/thoth/packages/remotion-composition/releases" in dockerfile
    assert "bun install --frozen-lockfile --production" in dockerfile


def test_the_player_is_only_a_development_dependency_of_the_renderer() -> None:
    """The parity harness may mount the Player; the service must never import it.

    The package itself is already inside the production image and was before this
    gate existed: `@remotion/bundler` depends on `@remotion/studio`, which depends
    on `@remotion/player`. What is checkable, and what this asserts, is that the
    renderer never declares it as a runtime dependency of its own.
    """
    manifest = json.loads(_repo_text("renderer/package.json"))

    assert manifest["devDependencies"]["@remotion/player"] == "4.0.538"
    assert "@remotion/player" not in manifest["dependencies"]


def test_parity_reference_image_is_pinned_and_separate() -> None:
    dockerfile = _repo_text("Dockerfile.renderer-f1")

    assert re.search(r"^FROM oven/bun:1\.4\.4@sha256:[0-9a-f]{64} AS ", dockerfile, re.MULTILINE)
    assert "THOTH_F1_BASE_DIGEST=sha256:" in dockerfile
    # Development dependencies are the point of this image: the Player lives there.
    assert "bun install --frozen-lockfile" in dockerfile
    assert "bun install --frozen-lockfile --production" not in dockerfile
    assert "packages/remotion-composition/releases/" in dockerfile
    assert "ensureBrowser" in dockerfile
    assert "ffprobe" in dockerfile


def _workflow_jobs() -> dict[str, str]:
    """Each job of the container workflow, by name, as its own text."""
    body = _repo_text(".github/workflows/container-image.yml").split("\njobs:\n", 1)[1]
    starts = [
        (found.group(1), found.start())
        for found in re.finditer(r"^  ([a-z][a-z0-9-]*):$", body, re.MULTILINE)
    ]
    ends = [*(at for _, at in starts[1:]), len(body)]
    return {name: body[at:end] for (name, at), end in zip(starts, ends, strict=True)}


def test_parity_reference_image_is_never_published() -> None:
    jobs = _workflow_jobs()
    assert "publish-image" in jobs

    # The reference image is a test image: no job that can publish may build it.
    for job in jobs.values():
        if "push: true" in job or "login-action" in job:
            assert "Dockerfile.renderer-f1" not in job


def _parity_job() -> str:
    """The template-release parity job, the only job that builds the reference."""
    return _workflow_jobs()["template-release-parity"]


def test_container_workflow_verifies_template_parity_in_the_reference_image() -> None:
    job = _parity_job()

    # One image, built from the pinned reference Dockerfile, for one platform.
    assert "file: Dockerfile.renderer-f1" in job
    assert "platforms: linux/amd64" in job
    assert "push: false" in job
    assert "load: true" in job
    assert "login-action" not in job
    # Its build identity travels into the report, so a candidate names what drew it.
    assert "THOTH_F1_IMAGE_ID=" in job
    assert "docker image inspect" in job
    # Every tracked capsule is verified against its approved golden set (story_mode-v1:
    # operator approval 2026-10-28).
    assert "for release in vertical_text_story-v1 story_mode-v1; do" in job
    assert 'verify-template-release.ts "${release}"' in job


def test_container_workflow_verifies_template_parity_without_a_network() -> None:
    job = _parity_job()

    assert "--network none" in job
    # A fresh root outside the checkout, mounted once and nowhere else.
    assert 'root="$(mktemp -d)"' in job
    assert job.count("THOTH_CONTROL_PLANE_ARTIFACT_ROOT=/var/lib/thoth/artifacts") == 1
    assert job.count('-v "${root}":/var/lib/thoth/artifacts') == 1
    assert "GITHUB_WORKSPACE" not in job


def test_container_workflow_never_promotes_or_uploads_a_candidate() -> None:
    workflow = _repo_text(".github/workflows/container-image.yml")

    # Promotion is an operator action against the repository, never a CI action.
    assert "promote-template-release" not in workflow
    assert "golden-manifest" not in workflow
    # A candidate is local evidence for one run, not an artifact CI hands around.
    assert "upload-artifact" not in _parity_job()


def test_the_yt_dlp_update_workflow_bumps_tests_merges_and_builds() -> None:
    workflow = _repo_text(".github/workflows/yt-dlp-update.yml")
    assert 'cron: "17 3 * * *"' in workflow
    assert "https://pypi.org/pypi/yt-dlp/json" in workflow
    assert "uv lock --project python --upgrade-package yt-dlp" in workflow
    assert 'uv run pytest -m "not live" -q' in workflow
    assert 'gh pr merge "$branch" --squash --delete-branch' in workflow
    assert "gh workflow run container-image.yml --ref master" in workflow
    # The image build must accept the dispatch the update workflow sends.
    assert "workflow_dispatch:" in _repo_text(".github/workflows/container-image.yml")


def test_a_dispatched_build_publishes_and_smokes_like_a_push() -> None:
    # The yt-dlp update workflow merges with the default token, whose push starts no
    # workflow, then dispatches this one; the dispatch must publish the image.
    jobs = _workflow_jobs()
    for name in ("publish-image", "stack-smoke"):
        assert "github.event_name == 'workflow_dispatch'" in jobs[name], name


def test_yt_dlp_is_pinned_once() -> None:
    # The acquisition extra holds the only pin since Scout's extra went (2026-10-30).
    pyproject = _repo_text("python/pyproject.toml")
    assert len(re.findall(r'"yt-dlp==([0-9.]+)"', pyproject)) == 1


def test_the_yt_dlp_update_workflow_trusts_no_unchecked_input() -> None:
    workflow = _repo_text(".github/workflows/yt-dlp-update.yml")
    # PyPI's answer must look like a yt-dlp date version before it reaches sed.
    assert "grep -Eq '^[0-9]{4}\\.[0-9]{1,2}\\.[0-9]{1,2}(\\.[0-9]+)?$'" in workflow
    # The tests run newly published code; the checkout keeps no token while they do.
    assert "persist-credentials: false" in workflow
    assert "gh auth setup-git" in workflow
    # A newer bump supersedes an older pull request left open.
    assert 'gh pr close "$old" --delete-branch' in workflow


def test_dockerfile_prepares_account_profiles_camoufox_and_timezones() -> None:
    dockerfile = _repo_text("Dockerfile")
    assert "/var/lib/thoth/artifacts /var/lib/thoth/account-profiles" in dockerfile
    assert "test -w /var/lib/thoth/account-profiles" in dockerfile
    assert "python -m camoufox fetch" in dockerfile
    assert "test -d /home/thoth/.cache/camoufox" in dockerfile
    # Account timezones are validated with zoneinfo; tzdata in the lock is Windows-only.
    assert "test -f /usr/share/zoneinfo/Asia/Jakarta" in dockerfile


def test_container_workflow_prepares_the_account_profiles_bind_source() -> None:
    # Compose long-syntax binds never create a missing host path.
    workflow = _repo_text(".github/workflows/container-image.yml")
    assert '"${root}"/account-profiles' in workflow
    assert 'sudo chmod 700 "${root}/account-profiles"' in workflow


def test_dockerfile_pins_camoufox_and_proves_it_launches() -> None:
    # Task 10 live gate 2026-10-14: the fetched browser could not start (no libgtk-3), and
    # `fetch` alone installs whatever the stable channel holds that day.
    dockerfile = _repo_text("Dockerfile")
    assert "python -m playwright install-deps firefox" in dockerfile
    assert "python -m camoufox set official/stable/156.0.1-beta.36" in dockerfile
    assert "Camoufox(headless=True)" in dockerfile


def test_image_jobs_free_runner_disk_before_docker() -> None:
    # CI run 38526701258: the publish runner ran out of disk once the image carried
    # Camoufox's browser (about 2.4 GB unpacked).
    workflow = _repo_text(".github/workflows/container-image.yml")
    for job, docker_step in (
        ("validate-image", "name: Set up Docker Buildx"),
        ("publish-image", "name: Set up Docker Buildx"),
        ("stack-smoke", "name: Log in to GHCR"),
    ):
        section = workflow.split(f"\n  {job}:", 1)[1].split("\n  stack-smoke:", 1)[0]
        assert "name: Free runner disk" in section, job
        assert section.index("name: Free runner disk") < section.index(docker_step), job


def test_heavy_layers_come_before_the_source_so_a_code_change_reuses_them() -> None:
    # Deploy 2026-10-14: speech models and Camoufox (3.7 GB compressed) were rebuilt after
    # every source change, so each deploy re-downloaded them.
    dockerfile = _repo_text("Dockerfile")
    source = dockerfile.index("COPY --chown=thoth:thoth python/src/")
    assert dockerfile.index("fetch_speech_models.py \\") < source
    assert dockerfile.index("python -m camoufox fetch") < source


def test_the_embedding_model_is_pinned_and_fetched_with_the_speech_models() -> None:
    script = _repo_text("docker/fetch_speech_models.py")
    assert "paraphrase-multilingual-MiniLM-L12-v2" in script
    assert "e8f8c211226b894fcb81acc59f3b34ba3efd5f42" in script
    # fp32, not a quantized export: int8 kernels score differently per CPU instruction set.
    assert '"onnx/model.onnx"' in script
    assert "10f7a088420252b26caf819236ca2c9d2987afd0fc06fec7553b542a5655a05a" in script
    assert "fetch_embedding(arguments.out)" in script
    dockerfile = _repo_text("Dockerfile")
    assert dockerfile.index("fetch_speech_models.py \\") < dockerfile.index(
        "COPY --chown=thoth:thoth python/src/"
    )


def test_the_deploy_imports_reports_with_the_old_worker_stopped() -> None:
    script = _repo_text("scripts/ops/deploy-stage1.sh")
    order = [
        script.index("editor migrate"),
        script.index("stop worker"),
        script.index("reports import"),
        script.index('" invalid=0"'),
        script.index("up -d --wait"),
    ]
    assert order == sorted(order)


def test_web_serves_missing_assets_as_404_and_publishes_domain_ports() -> None:
    root = Path(__file__).resolve().parents[3]
    caddyfile = (root / "deploy/web/Caddyfile").read_text(encoding="utf-8")
    assets = caddyfile[caddyfile.index("handle /assets/*") :]
    assets = assets[: assets.index("}") + 1]
    assert "file_server" in assets and "try_files" not in assets
    overlay = (root / "compose.stage1.web.yml").read_text(encoding="utf-8")
    assert ":8080" in overlay and ":8443" in overlay  # host 80/443 map here for a domain
    assert "THOTH_WEB_HTTP_BIND" in overlay and "THOTH_WEB_HTTPS_BIND" in overlay


def test_the_smoke_registers_its_project_before_any_project_route() -> None:
    """Project routes answer 404 for an unregistered project (workspace isolation), so every
    driver step that calls one first registers the smoke project in the bootstrap workspace."""
    script = _repo_text("docker/test-renderer-offline.sh")
    for name in ("upload", "seed"):
        body = script[script.index(f"def {name}(") :]
        body = body[: body.index("\ndef ", 1)]
        assert "ensure_project()" in body, name


def test_the_xendit_webhook_is_proxied_to_the_api() -> None:
    """Billing spec 2.2: Xendit posts to /billing/webhooks/xendit; the SPA must not answer it."""
    caddyfile = _repo_text("deploy/web/Caddyfile")
    backend = next(line for line in caddyfile.splitlines() if "@backend path" in line)
    assert "/billing/webhooks/*" in backend.split()


def test_the_site_pins_browsers_to_https_once_they_reach_it() -> None:
    """Audit A3: browsers ignore HSTS over plain HTTP, so a local site is unaffected, while a
    domain deploy keeps every later visit, and its cookies, on HTTPS."""
    caddyfile = _repo_text("deploy/web/Caddyfile")
    assert 'Strict-Transport-Security "max-age=31536000"' in caddyfile


def test_the_image_carries_the_bundled_sfx_and_their_licences() -> None:
    """Narration seeds the SFX from the image; only licensed files are ever seeded."""
    dockerfile = _repo_text("Dockerfile")
    assert "COPY --chown=thoth:thoth assets/sfx/ /opt/thoth/assets/sfx/" in dockerfile
    assert (
        "COPY --chown=thoth:thoth assets/asset_catalog.json /opt/thoth/assets/asset_catalog.json"
        in dockerfile
    )
    assert (REPOSITORY_ROOT / "assets/sfx/LICENSES.json").is_file()
