from __future__ import annotations

from typing import Any

API_VERSION = "kubevoip.com/v1alpha1"


def metadata(name: str, namespace: str | None) -> dict[str, Any]:
    data: dict[str, Any] = {"name": name}
    if namespace:
        data["namespace"] = namespace
    return data


def sip_user(
    *,
    name: str,
    namespace: str | None,
    extension: str,
    gateway: str,
    dial_policy: str,
    auth_username: str | None,
    caller_id: str | None,
    password_secret: str,
    password_key: str,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "gatewayRef": {"name": gateway},
        "dialPolicyRef": {"name": dial_policy},
        "extension": extension,
        "authUsername": auth_username or name,
        "passwordSecretRef": {"name": password_secret, "key": password_key},
    }
    if caller_id:
        spec["callerId"] = caller_id
    return {"apiVersion": API_VERSION, "kind": "SIPUser", "metadata": metadata(name, namespace), "spec": spec}


def sip_user_update(
    existing: dict[str, Any],
    *,
    namespace: str | None,
    extension: str | None,
    gateway: str | None,
    dial_policy: str | None,
    auth_username: str | None,
    caller_id: str | None,
    password_secret: str | None,
    password_key: str,
) -> dict[str, Any]:
    name = existing.get("metadata", {}).get("name")
    if not name:
        raise ValueError("existing SIPUser is missing metadata.name")
    spec = dict(existing.get("spec", {}))
    if gateway:
        spec["gatewayRef"] = {"name": gateway}
    if dial_policy:
        spec["dialPolicyRef"] = {"name": dial_policy}
    if extension:
        spec["extension"] = extension
    if auth_username:
        spec["authUsername"] = auth_username
    if caller_id:
        spec["callerId"] = caller_id
    if password_secret:
        spec["passwordSecretRef"] = {"name": password_secret, "key": password_key}
    if spec == existing.get("spec", {}):
        raise ValueError("at least one changed field must be provided")
    return {
        "apiVersion": existing.get("apiVersion", API_VERSION),
        "kind": "SIPUser",
        "metadata": metadata(name, namespace or existing.get("metadata", {}).get("namespace")),
        "spec": spec,
    }


def sip_trunk(
    *,
    name: str,
    namespace: str | None,
    gateway: str,
    termination_uri: str,
    inbound_dial_policy: str,
    allowed_source_cidrs: tuple[str, ...],
    caller_id_secret: str | None,
    caller_id_key: str,
    authentication_mode: str,
    digest_username_secret: str | None,
    digest_username_key: str,
    digest_password_secret: str | None,
    digest_password_key: str,
    digest_realm: str | None,
) -> dict[str, Any]:
    outbound: dict[str, Any] = {"authentication": {"mode": authentication_mode}}
    if caller_id_secret:
        outbound["callerIdSecretRef"] = {"name": caller_id_secret, "key": caller_id_key}
    if authentication_mode == "Digest":
        if not digest_username_secret or not digest_password_secret:
            raise ValueError(
                "--digest-username-secret and --digest-password-secret are required for Digest authentication"
            )
        digest: dict[str, Any] = {
            "usernameSecretRef": {"name": digest_username_secret, "key": digest_username_key},
            "passwordSecretRef": {"name": digest_password_secret, "key": digest_password_key},
        }
        if digest_realm:
            digest["realm"] = digest_realm
        outbound["authentication"]["digest"] = digest
    spec = {
        "gatewayRef": {"name": gateway},
        "terminationUri": termination_uri,
        "inbound": {
            "dialPolicyRef": {"name": inbound_dial_policy},
            "allowedSourceCidrs": list(allowed_source_cidrs),
        },
        "outbound": outbound,
    }
    return {"apiVersion": API_VERSION, "kind": "SIPTrunk", "metadata": metadata(name, namespace), "spec": spec}


def call_route(
    *,
    name: str,
    namespace: str | None,
    gateway: str,
    scope: str,
    priority: int,
    match: str,
    target_user: str | None,
    target_trunk: str | None,
    target_asterisk_pool: str | None,
    target_extension: str | None,
) -> dict[str, Any]:
    targets = [target for target in (target_user, target_trunk, target_asterisk_pool) if target]
    if len(targets) != 1:
        raise ValueError("exactly one route target is required")
    target: dict[str, Any]
    if target_user:
        target = {"sipUserRef": target_user}
    elif target_trunk:
        target = {"trunkRef": target_trunk}
    else:
        if not target_extension:
            raise ValueError("--target-extension is required with --target-asterisk-pool")
        target = {"asteriskPoolRef": target_asterisk_pool, "extension": target_extension}
    spec = {
        "gatewayRef": {"name": gateway},
        "scopeRef": {"name": scope},
        "priority": priority,
        "match": {"calledNumber": match},
        "target": target,
    }
    return {"apiVersion": API_VERSION, "kind": "CallRoute", "metadata": metadata(name, namespace), "spec": spec}


def call_scope(*, name: str, namespace: str | None, gateway: str) -> dict[str, Any]:
    return {
        "apiVersion": API_VERSION,
        "kind": "CallScope",
        "metadata": metadata(name, namespace),
        "spec": {"gatewayRef": {"name": gateway}},
    }


def dial_policy(*, name: str, namespace: str | None, gateway: str, scopes: tuple[str, ...]) -> dict[str, Any]:
    return {
        "apiVersion": API_VERSION,
        "kind": "DialPolicy",
        "metadata": metadata(name, namespace),
        "spec": {"gatewayRef": {"name": gateway}, "scopes": [{"name": scope} for scope in scopes]},
    }


def secret(*, name: str, namespace: str | None, key: str, value: str) -> dict[str, Any]:
    import base64

    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": metadata(name, namespace),
        "type": "Opaque",
        "data": {key: base64.b64encode(value.encode()).decode()},
    }
