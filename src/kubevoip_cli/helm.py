from __future__ import annotations

import subprocess

HELM_REPO_NAME = "kubevoip"
HELM_REPO_URL = "https://charts.kubevoip.com"
HELM_CHART = "kubevoip/kubevoip"
OCI_CHART = "oci://ghcr.io/kubevoip/charts/kubevoip"


class HelmError(RuntimeError):
    pass


def run(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True)
    except FileNotFoundError as exc:
        raise HelmError("helm is required but was not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise HelmError(f"helm command failed with exit code {exc.returncode}: {' '.join(args)}") from exc


def install_operator(
    *,
    release_name: str,
    namespace: str,
    version: str,
    kubeconfig: str | None,
    kube_context: str | None,
    oci: bool,
    create_namespace: bool,
    wait: bool,
    timeout: str | None,
    values: tuple[str, ...],
    set_values: tuple[str, ...],
) -> None:
    if not oci:
        run(["helm", "repo", "add", HELM_REPO_NAME, HELM_REPO_URL, "--force-update"])
        run(["helm", "repo", "update"])

    command = [
        "helm",
        "upgrade",
        "--install",
        release_name,
        OCI_CHART if oci else HELM_CHART,
        "--version",
        version,
        "--namespace",
        namespace,
    ]
    if kubeconfig:
        command.extend(["--kubeconfig", kubeconfig])
    if kube_context:
        command.extend(["--kube-context", kube_context])
    if create_namespace:
        command.append("--create-namespace")
    if wait:
        command.append("--wait")
    if timeout:
        command.extend(["--timeout", timeout])
    for value_file in values:
        command.extend(["-f", value_file])
    for value in set_values:
        command.extend(["--set", value])
    run(command)
