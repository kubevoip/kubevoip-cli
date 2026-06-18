from pathlib import Path

import yaml

from kubevoip_cli import builders, schema

FIXTURE = Path(__file__).parent / "fixtures" / "platform-crds.yaml"


def resources() -> list[schema.ResourceDescriptor]:
    return schema.parse_resources(FIXTURE.read_text())


def test_parses_current_crds() -> None:
    parsed = resources()
    kinds = {resource.kind for resource in parsed}
    assert {"SIPUser", "SIPTrunk", "CallRoute", "SIPGateway", "MediaRelay"}.issubset(kinds)


def test_matches_resource_aliases() -> None:
    parsed = resources()
    assert schema.find_resource(parsed, "sipuser").kind == "SIPUser"
    assert schema.find_resource(parsed, "sipusers").kind == "SIPUser"
    assert schema.find_resource(parsed, "SIPUser").kind == "SIPUser"


def test_explains_nested_field() -> None:
    resource = schema.find_resource(resources(), "sipuser")
    path, field, required = schema.field_schema(resource, "spec.passwordSecretRef")
    assert path == "spec.passwordSecretRef"
    assert schema.schema_type(field) == "object"
    assert required is True
    assert sorted(field["properties"]) == ["key", "name"]


def test_generates_skeleton_manifest() -> None:
    resource = schema.find_resource(resources(), "sipuser")
    manifest = schema.manifest_for(resource, name="alice", namespace="telephony")
    assert manifest["apiVersion"] == "kubevoip.com/v1alpha1"
    assert manifest["kind"] == "SIPUser"
    assert manifest["metadata"] == {"name": "alice", "namespace": "telephony"}
    assert set(manifest["spec"]) == {"gatewayRef", "dialPolicyRef", "extension", "authUsername", "passwordSecretRef"}


def test_user_builder_outputs_sipuser() -> None:
    manifest = builders.sip_user(
        name="alice",
        namespace="telephony",
        extension="100",
        gateway="main",
        dial_policy="internal-external",
        auth_username=None,
        caller_id="Alice <100>",
        password_secret="alice-sip",
        password_key="password",
    )
    assert manifest["kind"] == "SIPUser"
    assert manifest["spec"]["authUsername"] == "alice"
    assert manifest["spec"]["passwordSecretRef"] == {"name": "alice-sip", "key": "password"}


def test_user_update_outputs_merged_sipuser() -> None:
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
    manifest = builders.sip_user_update(
        existing,
        namespace="telephony",
        extension="101",
        gateway=None,
        dial_policy=None,
        auth_username=None,
        caller_id="Alice <101>",
        password_secret=None,
        password_key="password",
    )
    assert manifest["kind"] == "SIPUser"
    assert manifest["metadata"] == {"name": "alice", "namespace": "telephony"}
    assert manifest["spec"]["extension"] == "101"
    assert manifest["spec"]["callerId"] == "Alice <101>"
    assert manifest["spec"]["passwordSecretRef"] == {"name": "alice-sip", "key": "password"}


def test_secret_builder_encodes_value() -> None:
    manifest = builders.secret(name="alice-sip", namespace="telephony", key="password", value="secret")
    assert manifest["kind"] == "Secret"
    assert manifest["data"]["password"] != "secret"
    assert yaml.safe_dump(manifest)


def test_trunk_builder_outputs_digest_refs_without_values() -> None:
    manifest = builders.sip_trunk(
        name="primary",
        namespace="telephony",
        gateway="main",
        termination_uri="provider.example.net",
        inbound_dial_policy="external-inbound",
        allowed_source_cidrs=("203.0.113.0/24",),
        caller_id_secret="caller-id",
        caller_id_key="callerId",
        authentication_mode="Digest",
        digest_username_secret="provider-auth",
        digest_username_key="username",
        digest_password_secret="provider-auth",
        digest_password_key="password",
        digest_realm="provider.example.net",
    )
    auth = manifest["spec"]["outbound"]["authentication"]
    assert auth["mode"] == "Digest"
    assert auth["digest"]["usernameSecretRef"] == {"name": "provider-auth", "key": "username"}
    assert auth["digest"]["passwordSecretRef"] == {"name": "provider-auth", "key": "password"}
    assert "provider-password" not in yaml.safe_dump(manifest)
