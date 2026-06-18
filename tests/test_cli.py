from pathlib import Path

from click.testing import CliRunner

from kubevoip_cli.main import cli

FIXTURE = str(Path(__file__).parent / "fixtures" / "platform-crds.yaml")


def invoke(args: list[str]):
    return CliRunner().invoke(cli, ["--schema-file", FIXTURE, *args])


def test_help() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Work with KubeVoIP" in result.output


def test_api_resources() -> None:
    result = invoke(["api-resources"])
    assert result.exit_code == 0
    assert "SIPUser" in result.output
    assert "CallRoute" in result.output


def test_manifest_sipuser() -> None:
    result = invoke(["--namespace", "telephony", "manifest", "sipuser", "--name", "alice"])
    assert result.exit_code == 0
    assert "kind: SIPUser" in result.output
    assert "namespace: telephony" in result.output


def test_explain_nested_field() -> None:
    result = invoke(["explain", "sipuser.spec.passwordSecretRef"])
    assert result.exit_code == 0
    assert "SIPUser.spec.passwordSecretRef" in result.output
    assert "Fields: key, name" in result.output


def test_user_create_dry_run() -> None:
    result = invoke(
        [
            "--namespace",
            "telephony",
            "user",
            "create",
            "alice",
            "--extension",
            "100",
            "--gateway",
            "main",
            "--dial-policy",
            "internal-external",
            "--password-secret",
            "alice-sip",
            "--dry-run",
        ]
    )
    assert result.exit_code == 0
    assert "kind: SIPUser" in result.output
    assert "authUsername: alice" in result.output


def test_route_requires_exactly_one_target() -> None:
    result = invoke(
        [
            "route",
            "create",
            "bad",
            "--gateway",
            "main",
            "--scope",
            "internal",
            "--priority",
            "100",
            "--match",
            "100",
            "--dry-run",
        ]
    )
    assert result.exit_code != 0
    assert "exactly one route target" in result.output


def test_trunk_digest_requires_secret_refs() -> None:
    result = invoke(
        [
            "trunk",
            "create",
            "primary",
            "--gateway",
            "main",
            "--termination-uri",
            "provider.example.net",
            "--inbound-dial-policy",
            "external-inbound",
            "--allowed-source-cidr",
            "203.0.113.0/24",
            "--authentication-mode",
            "Digest",
            "--dry-run",
        ]
    )
    assert result.exit_code != 0
    assert "--digest-username-secret" in result.output
