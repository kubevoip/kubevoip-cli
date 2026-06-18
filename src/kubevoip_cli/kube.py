from __future__ import annotations

from typing import Any

import yaml

from kubevoip_cli.schema import ResourceDescriptor, find_resource

FIELD_MANAGER = "kubevoip-cli"
APPLY_CONTENT_TYPE = "application/apply-patch+yaml"


class KubernetesError(RuntimeError):
    pass


def load_client(*, kubeconfig: str | None = None, context: str | None = None):
    try:
        from kubernetes import client, config
    except ImportError as exc:
        raise KubernetesError("the kubernetes package is required for cluster operations") from exc

    try:
        config.load_kube_config(config_file=kubeconfig, context=context)
    except Exception:
        config.load_incluster_config()
    return client


def manifest_namespace(manifest: dict[str, Any], default_namespace: str | None) -> str:
    namespace = manifest.get("metadata", {}).get("namespace") or default_namespace
    if not namespace:
        raise KubernetesError("--namespace is required for namespaced resources")
    return namespace


def server_side_apply(
    manifest: dict[str, Any],
    *,
    resource: ResourceDescriptor | None,
    namespace: str | None,
    kubeconfig: str | None = None,
    context: str | None = None,
    dry_run: bool,
) -> dict[str, Any]:
    client = load_client(kubeconfig=kubeconfig, context=context)
    dry_run_value = "All" if dry_run else None
    name = manifest.get("metadata", {}).get("name")
    if not name:
        raise KubernetesError("metadata.name is required")

    if manifest.get("apiVersion") == "v1" and manifest.get("kind") == "Secret":
        api = client.CoreV1Api()
        applied = api.patch_namespaced_secret(
            name=name,
            namespace=manifest_namespace(manifest, namespace),
            body=manifest,
            dry_run=dry_run_value,
            field_manager=FIELD_MANAGER,
            force=True,
            _content_type=APPLY_CONTENT_TYPE,
        )
        return applied.to_dict()

    if resource is None:
        kind = manifest.get("kind")
        raise KubernetesError(f"unsupported manifest kind {kind!r}; only KubeVoIP resources and Secrets are supported")

    api = client.CustomObjectsApi()
    if resource.scope == "Namespaced":
        return api.patch_namespaced_custom_object(
            group=resource.group,
            version=resource.version,
            namespace=manifest_namespace(manifest, namespace),
            plural=resource.plural,
            name=name,
            body=manifest,
            dry_run=dry_run_value,
            field_manager=FIELD_MANAGER,
            force=True,
            _content_type=APPLY_CONTENT_TYPE,
        )
    return api.patch_cluster_custom_object(
        group=resource.group,
        version=resource.version,
        plural=resource.plural,
        name=name,
        body=manifest,
        dry_run=dry_run_value,
        field_manager=FIELD_MANAGER,
        force=True,
        _content_type=APPLY_CONTENT_TYPE,
    )


def apply_manifest(
    manifest: dict[str, Any],
    *,
    resource: ResourceDescriptor | None,
    namespace: str | None,
    kubeconfig: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    server_side_apply(
        manifest,
        resource=resource,
        namespace=namespace,
        kubeconfig=kubeconfig,
        context=context,
        dry_run=True,
    )
    server_side_apply(
        manifest,
        resource=resource,
        namespace=namespace,
        kubeconfig=kubeconfig,
        context=context,
        dry_run=False,
    )
    return {"applied": 1}


def apply_yaml_file(
    path: str,
    *,
    resources: list[ResourceDescriptor],
    namespace: str | None,
    kubeconfig: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    with open(path) as stream:
        documents = [document for document in yaml.safe_load_all(stream) if isinstance(document, dict)]
    for document in documents:
        resource = None
        if document.get("apiVersion", "").startswith("kubevoip.com/"):
            try:
                resource = find_resource(resources, document.get("kind", ""))
            except KeyError as exc:
                raise KubernetesError(str(exc)) from exc
        apply_manifest(document, resource=resource, namespace=namespace, kubeconfig=kubeconfig, context=context)
    return {"applied": len(documents)}


def custom_api(*, kubeconfig: str | None = None, context: str | None = None):
    client = load_client(kubeconfig=kubeconfig, context=context)
    return client.CustomObjectsApi()


def list_custom(
    *,
    group: str,
    version: str,
    plural: str,
    namespace: str | None,
    scope: str,
    kubeconfig: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    api = custom_api(kubeconfig=kubeconfig, context=context)
    if scope == "Namespaced":
        if not namespace:
            raise KubernetesError("--namespace is required for namespaced resources")
        return api.list_namespaced_custom_object(group, version, namespace, plural)
    return api.list_cluster_custom_object(group, version, plural)


def get_custom(
    *,
    group: str,
    version: str,
    plural: str,
    name: str,
    namespace: str | None,
    scope: str,
    kubeconfig: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    api = custom_api(kubeconfig=kubeconfig, context=context)
    if scope == "Namespaced":
        if not namespace:
            raise KubernetesError("--namespace is required for namespaced resources")
        return api.get_namespaced_custom_object(group, version, namespace, plural, name)
    return api.get_cluster_custom_object(group, version, plural, name)
