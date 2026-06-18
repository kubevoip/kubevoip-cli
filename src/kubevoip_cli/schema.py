from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

GROUP = "kubevoip.com"


@dataclass(frozen=True)
class ResourceDescriptor:
    group: str
    version: str
    kind: str
    plural: str
    singular: str
    short_names: tuple[str, ...]
    scope: str
    schema: dict[str, Any]
    crd_name: str

    @property
    def api_version(self) -> str:
        return f"{self.group}/{self.version}"

    @property
    def aliases(self) -> set[str]:
        values = {self.kind, self.plural, self.singular, self.kind.lower(), self.plural.lower(), self.singular.lower()}
        values.update(self.short_names)
        values.update(name.lower() for name in self.short_names)
        return {normalize_resource_name(value) for value in values}


def normalize_resource_name(value: str) -> str:
    return value.replace("-", "").replace("_", "").lower()


def load_crd_documents(content: str) -> list[dict[str, Any]]:
    return [
        document
        for document in yaml.safe_load_all(content)
        if isinstance(document, dict)
        and document.get("kind") == "CustomResourceDefinition"
        and document.get("spec", {}).get("group") == GROUP
    ]


def parse_resources(content: str) -> list[ResourceDescriptor]:
    resources: list[ResourceDescriptor] = []
    for crd in load_crd_documents(content):
        spec = crd["spec"]
        version = next(version for version in spec["versions"] if version.get("storage") or version.get("served"))
        schema = version["schema"]["openAPIV3Schema"]
        names = spec["names"]
        resources.append(
            ResourceDescriptor(
                group=spec["group"],
                version=version["name"],
                kind=names["kind"],
                plural=names["plural"],
                singular=names["singular"],
                short_names=tuple(names.get("shortNames", [])),
                scope=spec["scope"],
                schema=schema,
                crd_name=crd["metadata"]["name"],
            )
        )
    return sorted(resources, key=lambda resource: resource.kind)


def find_resource(resources: list[ResourceDescriptor], name: str) -> ResourceDescriptor:
    normalized = normalize_resource_name(name)
    for resource in resources:
        if normalized in resource.aliases:
            return resource
    available = ", ".join(resource.singular for resource in resources)
    raise KeyError(f"unknown KubeVoIP resource {name!r}; available resources: {available}")


def spec_schema(resource: ResourceDescriptor) -> dict[str, Any]:
    return resource.schema.get("properties", {}).get("spec", {"type": "object", "properties": {}})


def field_schema(resource: ResourceDescriptor, path: str | None) -> tuple[str, dict[str, Any], bool]:
    if not path:
        return "spec", spec_schema(resource), "spec" in set(resource.schema.get("required", []))

    parts = path.split(".")
    if parts[0] == resource.singular.lower() or parts[0] == resource.kind.lower():
        parts = parts[1:]
    if parts and parts[0] == "spec":
        parts = parts[1:]

    schema = spec_schema(resource)
    required = set(schema.get("required", []))
    current_path = "spec"
    is_required = "spec" in set(resource.schema.get("required", []))

    for part in parts:
        if schema.get("type") == "array":
            schema = schema.get("items", {})
            required = set(schema.get("required", []))
        properties = schema.get("properties", {})
        if part not in properties:
            raise KeyError(f"field {current_path}.{part} does not exist on {resource.kind}")
        schema = properties[part]
        is_required = part in required
        required = set(schema.get("required", []))
        current_path = f"{current_path}.{part}"
    return current_path, schema, is_required


def schema_type(schema: dict[str, Any]) -> str:
    if "enum" in schema:
        return "enum(" + ", ".join(str(value) for value in schema["enum"]) + ")"
    if schema.get("type") == "array":
        return f"array[{schema_type(schema.get('items', {}))}]"
    return schema.get("type", "object")


def schema_constraints(schema: dict[str, Any]) -> list[str]:
    constraints: list[str] = []
    for key, label in (
        ("pattern", "pattern"),
        ("minLength", "minLength"),
        ("maxLength", "maxLength"),
        ("minimum", "minimum"),
        ("maximum", "maximum"),
        ("default", "default"),
    ):
        if key in schema:
            constraints.append(f"{label}={schema[key]}")
    for validation in schema.get("x-kubernetes-validations", []):
        if message := validation.get("message"):
            constraints.append(message)
    return constraints


def placeholder_for(schema: dict[str, Any], name: str) -> Any:
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    schema_kind = schema.get("type")
    if schema_kind == "integer":
        return 0
    if schema_kind == "number":
        return 0
    if schema_kind == "boolean":
        return False
    if schema_kind == "array":
        item = schema.get("items", {})
        if item.get("type") == "object":
            return [skeleton_from_schema(item, required_only=True)]
        return [placeholder_for(item, name)]
    if schema_kind == "object":
        return skeleton_from_schema(schema, required_only=True)
    if name == "key":
        return "password"
    return ""


def skeleton_from_schema(schema: dict[str, Any], *, required_only: bool) -> dict[str, Any]:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    result: dict[str, Any] = {}
    for name, child in properties.items():
        if required_only and name not in required:
            continue
        result[name] = placeholder_for(child, name)
    return result


def manifest_for(resource: ResourceDescriptor, *, name: str, namespace: str | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": name}
    if namespace and resource.scope == "Namespaced":
        metadata["namespace"] = namespace
    manifest: dict[str, Any] = {
        "apiVersion": resource.api_version,
        "kind": resource.kind,
        "metadata": metadata,
    }
    spec = skeleton_from_schema(spec_schema(resource), required_only=True)
    if spec or "spec" in set(resource.schema.get("required", [])):
        manifest["spec"] = spec
    return manifest

