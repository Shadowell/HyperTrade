"""Static guards for the CI / supply-chain configuration.

These read the workflow files as text (like tests/test_deployment_config.py) so they need no YAML
dependency. They pin the properties that are easy to lose in a later edit and expensive to notice:
a workflow only runs after the merge, so a regression here would otherwise surface in production.
"""

import re
from pathlib import Path

WORKFLOWS = Path(".github/workflows")


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _on_block(text: str) -> str:
    match = re.search(r"(?ms)^on:\n(?P<body>(?:[ \t]+.*\n|\n)+)", text)
    assert match is not None, "workflow has no top-level `on:` block"
    return match.group("body")


def test_ci_runs_on_pull_requests_and_on_main() -> None:
    # Without a pull_request trigger the only CI run happens after the merge, i.e. after the
    # deploy has already been started by the same push.
    triggers = _on_block(_workflow("ci.yml"))
    assert re.search(r"(?m)^  pull_request:", triggers)
    assert re.search(r"(?ms)^  push:\n    branches: \[main\]", triggers)


def test_backend_job_installs_strictly_from_the_lock() -> None:
    ci = _workflow("ci.yml")
    assert "uv sync --locked --all-extras --dev" in ci
    assert not re.search(r"uv sync (?!.*--locked)", ci), "uv sync must always pass --locked"


def test_ci_lints_the_workflows_themselves() -> None:
    ci = _workflow("ci.yml")
    assert re.search(r"actionlint-py==\d+(\.\d+)+ actionlint", ci)


def test_actionlint_knows_the_custom_production_runner_label() -> None:
    labels = re.findall(r"runs-on: \[self-hosted, ([\w-]+)\]", _workflow("deploy.yml"))
    assert labels, "deploy.yml no longer targets a custom self-hosted runner label"
    config = Path(".github/actionlint.yaml").read_text(encoding="utf-8")
    for label in labels:
        assert f"- {label}" in config, f"actionlint.yaml must declare the runner label {label}"


def test_every_workflow_declares_a_least_privilege_token() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^permissions:\n  contents: read\n", text), (
            f"{path.name} must start from `permissions: contents: read` and widen per job only "
            "where a job needs it"
        )


def test_third_party_actions_are_pinned_to_commit_shas() -> None:
    # deploy.yml's `deploy` job runs on the self-hosted production runner; a moved or hijacked
    # tag would run attacker code on the production host. A 40-hex SHA plus a `# vN` comment
    # (Dependabot keeps both current) is immune to tag moves.
    uses = re.compile(r"(?m)^\s*(?:-\s+)?uses:\s+(?P<ref>\S+)(?P<rest>.*)$")
    seen = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for match in uses.finditer(path.read_text(encoding="utf-8")):
            ref = match.group("ref")
            if ref.startswith("./"):
                continue
            seen += 1
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), (
                f"{path.name}: `{ref}` must be pinned to a full commit SHA"
            )
            assert re.match(r"\s+#\s+v\d+", match.group("rest")), (
                f"{path.name}: `{ref}` needs a trailing `# vN` comment naming the pinned release"
            )
    assert seen >= 8, "expected the workflows to reference third-party actions"


def test_security_workflow_audits_what_the_image_ships() -> None:
    security = _workflow("security.yml")
    triggers = _on_block(security)
    assert "pull_request:" in triggers and "schedule:" in triggers

    # The audited set must be the production closure from the committed lock.
    export = re.search(r"uv export (?P<flags>[^\n]*(?:\n[ \t]+[^\n]*)*)", security)
    assert export is not None
    flags = export.group("flags")
    assert "--locked" in flags and "--no-dev" in flags and "--no-emit-project" in flags

    assert re.search(r"uvx pip-audit==\d+(\.\d+)+ -r ", security), "pin the pip-audit version"
    assert "pnpm --dir frontend audit --prod" in security


def test_dockerfile_installs_the_same_closure_that_is_audited() -> None:
    # If the image stops installing with `--frozen --no-dev` the audit above no longer describes
    # what runs in production.
    dockerfile = Path("backend/Dockerfile").read_text(encoding="utf-8")
    runtime_installs = re.findall(r"uv sync (--frozen --no-dev[^\n]*)", dockerfile)
    assert len(runtime_installs) >= 2
    assert "--extra" not in runtime_installs[0] and "--extra" not in runtime_installs[1]


def test_codeql_scans_every_language_in_the_repository() -> None:
    codeql = _workflow("codeql.yml")
    match = re.search(r"language: \[(?P<langs>[^\]]+)\]", codeql)
    assert match is not None
    languages = {part.strip() for part in match.group("langs").split(",")}
    assert languages == {"python", "javascript-typescript", "actions"}
    assert "security-events: write" in codeql


def test_dependabot_covers_every_ecosystem_in_use() -> None:
    config = Path(".github/dependabot.yml").read_text(encoding="utf-8")
    assert re.search(r"package-ecosystem: uv\n    directory: /\n", config)
    assert re.search(r"package-ecosystem: npm\n    directory: /frontend\n", config)
    assert re.search(r"package-ecosystem: github-actions\n    directory: /\n", config)
    # the lock files these ecosystems maintain must exist
    assert Path("uv.lock").is_file() and Path("frontend/pnpm-lock.yaml").is_file()


def test_codeowners_names_a_default_owner_and_the_release_surfaces() -> None:
    owners = Path(".github/CODEOWNERS").read_text(encoding="utf-8")
    rules = [line.split() for line in owners.splitlines() if line and not line.startswith("#")]
    assert ["*", "@Shadowell"] in rules
    paths = {rule[0] for rule in rules}
    assert {"/.github/", "/deploy/", "/backend/alembic/", "/uv.lock"} <= paths
