from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

from kubevoip_cli.schema import GROUP

DEFAULT_PLATFORM_REPO = "kubevoip/kubevoip"
CACHE_ROOT = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache")) / "kubevoip-cli" / "platform-crds"
LATEST_CACHE_TTL_SECONDS = 3600


class DiscoveryError(RuntimeError):
    pass


def read_schema_file(path: str | Path) -> str:
    return Path(path).read_text()


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "kubevoip-cli",
    }
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_url(url: str, *, headers: dict[str, str] | None = None) -> bytes:
    try:
        with urlopen(Request(url, headers=headers or {}), timeout=30) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise DiscoveryError(f"failed to fetch {url}: {exc}") from exc


def latest_platform_ref() -> str:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_ROOT / "latest.json"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        if time.time() - cached.get("createdAt", 0) < LATEST_CACHE_TTL_SECONDS:
            return str(cached["tagName"])

    payload = json.loads(
        _read_url(
            f"https://api.github.com/repos/{DEFAULT_PLATFORM_REPO}/releases/latest",
            headers=_github_headers(),
        )
    )
    tag = payload["tag_name"]
    cache_file.write_text(json.dumps({"tagName": tag, "createdAt": time.time()}))
    return tag


def fetch_platform_crds(ref: str | None = None) -> str:
    ref = ref or latest_platform_ref()
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_ROOT / f"{ref}.yaml"
    if cache_file.exists():
        return cache_file.read_text()

    url = f"https://raw.githubusercontent.com/{DEFAULT_PLATFORM_REPO}/{ref}/config/crd/platform-crds.yaml"
    content = _read_url(url, headers={"User-Agent": "kubevoip-cli"}).decode()
    cache_file.write_text(content)
    return content


def load_cluster_crds(*, kubeconfig: str | None = None, context: str | None = None) -> str:
    try:
        from kubernetes import client, config
    except ImportError as exc:
        raise DiscoveryError("the kubernetes package is required for cluster schema discovery") from exc

    try:
        config.load_kube_config(config_file=kubeconfig, context=context)
    except Exception:
        config.load_incluster_config()

    api = client.ApiextensionsV1Api()
    documents = []
    for crd in api.list_custom_resource_definition().items:
        if crd.spec.group != GROUP:
            continue
        document = api.api_client.sanitize_for_serialization(crd)
        document.setdefault("apiVersion", "apiextensions.k8s.io/v1")
        document.setdefault("kind", "CustomResourceDefinition")
        documents.append(document)
    return "\n---\n".join(yaml.safe_dump(document, sort_keys=False) for document in documents)


def resolve_schema(
    *,
    schema_source: str,
    schema_file: str | None,
    platform_ref: str | None,
    kubeconfig: str | None,
    context: str | None,
) -> str:
    if schema_file:
        return read_schema_file(schema_file)
    if schema_source == "file":
        raise DiscoveryError("--schema-source=file requires --schema-file")
    if schema_source == "cluster":
        return load_cluster_crds(kubeconfig=kubeconfig, context=context)
    return fetch_platform_crds(platform_ref)
