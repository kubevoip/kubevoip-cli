from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from kubevoip_cli.main import cli

FIXTURE = str(Path(__file__).parent / "fixtures" / "platform-crds.yaml")


def invoke(args: list[str], input: str | None = None):
    return CliRunner().invoke(cli, ["--schema-file", FIXTURE, *args], input=input)


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


def test_auto_schema_uses_latest_for_manifest() -> None:
    with patch("kubevoip_cli.discovery.resolve_schema", return_value=Path(FIXTURE).read_text()) as resolve:
        result = CliRunner().invoke(cli, ["manifest", "sipuser", "--name", "alice"])
    assert result.exit_code == 0
    assert "kind: SIPUser" in result.output
    assert resolve.call_args.kwargs["schema_source"] == "latest"


def test_auto_schema_uses_cluster_for_get() -> None:
    with (
        patch("kubevoip_cli.discovery.resolve_schema", return_value=Path(FIXTURE).read_text()) as resolve,
        patch("kubevoip_cli.main.kube.list_custom", return_value={"items": []}),
    ):
        result = CliRunner().invoke(cli, ["--namespace", "telephony", "get", "sipuser"])
    assert result.exit_code == 0
    assert resolve.call_args.kwargs["schema_source"] == "cluster"


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


def test_user_update_dry_run_outputs_merged_manifest() -> None:
    existing = {
        "apiVersion": "kubevoip.com/v1alpha1",
        "kind": "SIPUser",
        "metadata": {"name": "alice", "namespace": "telephony"},
        "spec": {
            "gatewayRef": {"name": "main"},
            "dialPolicyRef": {"name": "internal"},
            "extension": "100",
            "authUsername": "alice",
            "passwordSecretRef": {"name": "alice-sip", "key": "password"},
        },
    }
    with patch("kubevoip_cli.main.kube.get_custom", return_value=existing):
        result = invoke(
            [
                "--namespace",
                "telephony",
                "user",
                "update",
                "alice",
                "--extension",
                "101",
                "--caller-id",
                "Alice <101>",
                "--dry-run",
            ]
        )
    assert result.exit_code == 0
    assert "kind: SIPUser" in result.output
    assert "extension: '101'" in result.output
    assert "passwordSecretRef" in result.output
    assert "name: alice-sip" in result.output


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


def test_quickstart_postgres_dry_run() -> None:
    result = invoke(["--namespace", "telephony", "quickstart", "postgres", "--dry-run"])
    assert result.exit_code == 0
    assert "kind: Secret" in result.output
    assert "kind: Service" in result.output
    assert "kind: Deployment" in result.output
    assert "postgres:16-alpine" in result.output


def test_init_demo_two_phones_dry_run() -> None:
    result = invoke(["--namespace", "telephony", "init", "--dry-run"])
    assert result.exit_code == 0
    assert "kind: Deployment" in result.output
    assert "kind: NetworkProfile" in result.output
    assert "kind: MediaRelay" in result.output
    assert "kind: SIPGateway" in result.output
    assert "kind: SIPUser" in result.output
    assert "name: alice" in result.output
    assert "match:" in result.output


def test_init_existing_database_uses_supplied_secret_name() -> None:
    result = invoke(
        [
            "--namespace",
            "telephony",
            "init",
            "--database",
            "existing",
            "--database-secret",
            "managed-postgres",
            "--dry-run",
        ]
    )
    assert result.exit_code == 0
    assert "kind: Deployment" not in result.output
    assert "name: managed-postgres" in result.output
    assert "kind: SIPGateway" in result.output


def test_init_existing_database_can_create_secret_from_stdin() -> None:
    result = invoke(
        [
            "--namespace",
            "telephony",
            "init",
            "--database",
            "existing",
            "--postgres-host",
            "postgres.example.net",
            "--postgres-password-stdin",
            "--dry-run",
        ],
        input="secret-password",
    )
    assert result.exit_code == 0
    assert "kind: Secret" in result.output
    assert "postgres.example.net" not in result.output
    assert "secret-password" not in result.output


def test_init_existing_database_secret_requires_host() -> None:
    result = invoke(
        [
            "--namespace",
            "telephony",
            "init",
            "--database",
            "existing",
            "--postgres-password-stdin",
            "--dry-run",
        ],
        input="secret-password",
    )
    assert result.exit_code != 0
    assert "--postgres-host is required" in result.output


def test_network_profile_create_dry_run() -> None:
    result = invoke(["--namespace", "telephony", "network-profile", "create", "public", "--dry-run"])
    assert result.exit_code == 0
    assert "kind: NetworkProfile" in result.output
    assert "source: Service" in result.output


def test_media_relay_create_dry_run() -> None:
    result = invoke(
        [
            "--namespace",
            "telephony",
            "media-relay",
            "create",
            "main",
            "--network-profile",
            "public",
            "--dry-run",
        ]
    )
    assert result.exit_code == 0
    assert "kind: MediaRelay" in result.output
    assert "start: 20000" in result.output


def test_gateway_create_dry_run() -> None:
    result = invoke(
        [
            "--namespace",
            "telephony",
            "gateway",
            "create",
            "main",
            "--database-secret",
            "postgres-app",
            "--network-profile",
            "public",
            "--media-relay",
            "main",
            "--dry-run",
        ]
    )
    assert result.exit_code == 0
    assert "kind: SIPGateway" in result.output
    assert "databaseSecretRef" in result.output


def test_database_secret_dry_run_from_stdin() -> None:
    result = invoke(
        [
            "--namespace",
            "telephony",
            "secret",
            "database",
            "postgres-app",
            "--host",
            "postgres.example.net",
            "--dbname",
            "kubevoip",
            "--user",
            "kubevoip",
            "--password-stdin",
            "--dry-run",
        ],
        input="secret-password",
    )
    assert result.exit_code == 0
    assert "kind: Secret" in result.output
    assert "postgres.example.net" not in result.output
    assert "secret-password" not in result.output
