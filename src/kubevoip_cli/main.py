from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from kubevoip_cli import __version__, builders, discovery, kube, render, schema


class Context:
    def __init__(
        self,
        *,
        namespace: str | None,
        kubeconfig: str | None,
        kube_context: str | None,
        schema_source: str,
        schema_file: str | None,
        platform_ref: str | None,
        output: str,
    ) -> None:
        self.namespace = namespace
        self.kubeconfig = kubeconfig
        self.kube_context = kube_context
        self.schema_source = schema_source
        self.schema_file = schema_file
        self.platform_ref = platform_ref
        self.output = output
        self._resources: list[schema.ResourceDescriptor] | None = None

    def resources(self) -> list[schema.ResourceDescriptor]:
        if self._resources is None:
            content = discovery.resolve_schema(
                schema_source=self.schema_source,
                schema_file=self.schema_file,
                platform_ref=self.platform_ref,
                kubeconfig=self.kubeconfig,
                context=self.kube_context,
            )
            self._resources = schema.parse_resources(content)
        return self._resources

    def resource(self, name: str) -> schema.ResourceDescriptor:
        try:
            return schema.find_resource(self.resources(), name)
        except KeyError as exc:
            raise click.ClickException(str(exc)) from exc


pass_context = click.make_pass_decorator(Context)


@click.group()
@click.option("--namespace", "-n", help="Kubernetes namespace for namespaced resources.")
@click.option("--kubeconfig", help="Path to kubeconfig.")
@click.option("--context", "kube_context", help="Kubeconfig context.")
@click.option(
    "--schema-file",
    type=click.Path(exists=True, dir_okay=False),
    help="Read KubeVoIP CRDs from a local file.",
)
@click.option("--platform-ref", help="KubeVoIP platform git ref to fetch CRDs from, for example v0.5.0.")
@click.option("--schema-source", type=click.Choice(["latest", "cluster", "file"]), default="latest", show_default=True)
@click.option("--output", "-o", type=click.Choice(["table", "yaml", "json"]), default="table", show_default=True)
@click.pass_context
def cli(
    ctx: click.Context,
    namespace: str | None,
    kubeconfig: str | None,
    kube_context: str | None,
    schema_file: str | None,
    platform_ref: str | None,
    schema_source: str,
    output: str,
) -> None:
    """Work with KubeVoIP Kubernetes resources."""
    ctx.obj = Context(
        namespace=namespace,
        kubeconfig=kubeconfig,
        kube_context=kube_context,
        schema_source=schema_source,
        schema_file=schema_file,
        platform_ref=platform_ref,
        output=output,
    )


@cli.command()
def version() -> None:
    """Show the CLI version."""
    click.echo(f"kubevoip {__version__}")


@cli.command("api-resources")
@pass_context
def api_resources(ctx: Context) -> None:
    """List KubeVoIP resources discovered from CRDs."""
    rows = [
        [resource.kind, resource.singular, resource.plural, ",".join(resource.short_names) or "-", resource.scope]
        for resource in ctx.resources()
    ]
    if ctx.output == "table":
        click.echo(render.table(["Kind", "Singular", "Plural", "Short names", "Scope"], rows), nl=False)
    else:
        click.echo(
            render.output(
                [
                    {
                        "kind": resource.kind,
                        "singular": resource.singular,
                        "plural": resource.plural,
                        "shortNames": list(resource.short_names),
                        "scope": resource.scope,
                        "apiVersion": resource.api_version,
                    }
                    for resource in ctx.resources()
                ],
                fmt=ctx.output,
            ),
            nl=False,
        )


@cli.command()
@click.argument("target")
@pass_context
def explain(ctx: Context, target: str) -> None:
    """Explain a KubeVoIP resource or field."""
    parts = target.split(".", 1)
    resource = ctx.resource(parts[0])
    path = parts[1] if len(parts) > 1 else None
    try:
        field_path, field, required = schema.field_schema(resource, path)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    data = {
        "resource": resource.kind,
        "field": field_path,
        "type": schema.schema_type(field),
        "required": required,
        "constraints": schema.schema_constraints(field),
        "properties": sorted(field.get("properties", {}).keys()),
    }
    if ctx.output == "table":
        click.echo(f"{data['resource']}.{data['field']}")
        click.echo(f"Type: {data['type']}")
        click.echo(f"Required: {data['required']}")
        if data["constraints"]:
            click.echo("Constraints: " + "; ".join(data["constraints"]))
        if data["properties"]:
            click.echo("Fields: " + ", ".join(data["properties"]))
    else:
        click.echo(render.output(data, fmt=ctx.output), nl=False)


@cli.command()
@click.argument("resource_name")
@click.argument("name", required=False)
@pass_context
def get(ctx: Context, resource_name: str, name: str | None) -> None:
    """Get KubeVoIP resources from the current cluster."""
    resource = ctx.resource(resource_name)
    try:
        if name:
            result = kube.get_custom(
                group=resource.group,
                version=resource.version,
                plural=resource.plural,
                name=name,
                namespace=ctx.namespace,
                scope=resource.scope,
                kubeconfig=ctx.kubeconfig,
                context=ctx.kube_context,
            )
        else:
            result = kube.list_custom(
                group=resource.group,
                version=resource.version,
                plural=resource.plural,
                namespace=ctx.namespace,
                scope=resource.scope,
                kubeconfig=ctx.kubeconfig,
                context=ctx.kube_context,
            )
    except kube.KubernetesError as exc:
        raise click.ClickException(str(exc)) from exc
    if ctx.output == "table" and not name:
        rows = [
            [
                item["metadata"]["name"],
                item.get("status", {}).get("phase", "-"),
                item["metadata"].get("namespace", ctx.namespace or "-"),
            ]
            for item in result.get("items", [])
        ]
        click.echo(render.table(["Name", "Phase", "Namespace"], rows), nl=False)
    else:
        click.echo(render.output(result, fmt="json" if ctx.output == "json" else "yaml"), nl=False)


@cli.command()
@click.argument("resource_name")
@click.option("--name", required=True, help="Resource name.")
@pass_context
def manifest(ctx: Context, resource_name: str, name: str) -> None:
    """Generate a skeleton manifest from a CRD schema."""
    resource = ctx.resource(resource_name)
    click.echo(render.yaml_dump(schema.manifest_for(resource, name=name, namespace=ctx.namespace)), nl=False)


@cli.command("apply")
@click.option("-f", "filename", type=click.Path(exists=True, dir_okay=False), required=True)
@pass_context
def apply_file(ctx: Context, filename: str) -> None:
    """Server-side dry-run, then apply a YAML file."""
    try:
        result = kube.apply_yaml_file(
            filename,
            resources=ctx.resources(),
            namespace=ctx.namespace,
            kubeconfig=ctx.kubeconfig,
            context=ctx.kube_context,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render.output(result, fmt="json" if ctx.output == "json" else "yaml"), nl=False)


def emit_or_apply(ctx: Context, manifest: dict[str, Any], *, dry_run: bool, output_format: str) -> None:
    if dry_run:
        click.echo(render.output(manifest, fmt="json" if output_format == "json" else "yaml"), nl=False)
        return
    try:
        resource = None
        if manifest.get("apiVersion", "").startswith("kubevoip.com/"):
            resource = ctx.resource(manifest["kind"])
        result = kube.apply_manifest(
            manifest,
            resource=resource,
            namespace=ctx.namespace,
            kubeconfig=ctx.kubeconfig,
            context=ctx.kube_context,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render.output(result, fmt="json" if output_format == "json" else "yaml"), nl=False)


@cli.group()
def user() -> None:
    """Manage SIPUser resources."""


@user.command("create")
@click.argument("name")
@click.option("--extension", required=True)
@click.option("--gateway", required=True)
@click.option("--dial-policy", required=True)
@click.option("--auth-username")
@click.option("--caller-id")
@click.option("--password-secret", required=True)
@click.option("--password-key", default="password", show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def user_create(
    ctx: Context,
    name: str,
    extension: str,
    gateway: str,
    dial_policy: str,
    auth_username: str | None,
    caller_id: str | None,
    password_secret: str,
    password_key: str,
    dry_run: bool,
    output: str,
) -> None:
    emit_or_apply(
        ctx,
        builders.sip_user(
            name=name,
            namespace=ctx.namespace,
            extension=extension,
            gateway=gateway,
            dial_policy=dial_policy,
            auth_username=auth_username,
            caller_id=caller_id,
            password_secret=password_secret,
            password_key=password_key,
        ),
        dry_run=dry_run,
        output_format=output,
    )


@user.command("update")
@click.argument("name")
@click.option("--extension")
@click.option("--gateway")
@click.option("--dial-policy")
@click.option("--auth-username")
@click.option("--caller-id")
@click.option("--password-secret")
@click.option("--password-key", default="password", show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def user_update(
    ctx: Context,
    name: str,
    extension: str | None,
    gateway: str | None,
    dial_policy: str | None,
    auth_username: str | None,
    caller_id: str | None,
    password_secret: str | None,
    password_key: str,
    dry_run: bool,
    output: str,
) -> None:
    """Update a SIPUser by merging changes into the live resource."""
    try:
        resource = ctx.resource("sipuser")
        existing = kube.get_custom(
            group=resource.group,
            version=resource.version,
            plural=resource.plural,
            name=name,
            namespace=ctx.namespace,
            scope=resource.scope,
            kubeconfig=ctx.kubeconfig,
            context=ctx.kube_context,
        )
        manifest = builders.sip_user_update(
            existing,
            namespace=ctx.namespace,
            extension=extension,
            gateway=gateway,
            dial_policy=dial_policy,
            auth_username=auth_username,
            caller_id=caller_id,
            password_secret=password_secret,
            password_key=password_key,
        )
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    emit_or_apply(ctx, manifest, dry_run=dry_run, output_format=output)


@cli.group()
def trunk() -> None:
    """Manage SIPTrunk resources."""


@trunk.command("create")
@click.argument("name")
@click.option("--gateway", required=True)
@click.option("--termination-uri", required=True)
@click.option("--inbound-dial-policy", required=True)
@click.option("--allowed-source-cidr", multiple=True, required=True)
@click.option("--caller-id-secret")
@click.option("--caller-id-key", default="callerId", show_default=True)
@click.option("--authentication-mode", type=click.Choice(["None", "Digest"]), default="None", show_default=True)
@click.option("--digest-username-secret")
@click.option("--digest-username-key", default="username", show_default=True)
@click.option("--digest-password-secret")
@click.option("--digest-password-key", default="password", show_default=True)
@click.option("--digest-realm")
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def trunk_create(
    ctx: Context,
    name: str,
    gateway: str,
    termination_uri: str,
    inbound_dial_policy: str,
    allowed_source_cidr: tuple[str, ...],
    caller_id_secret: str | None,
    caller_id_key: str,
    authentication_mode: str,
    digest_username_secret: str | None,
    digest_username_key: str,
    digest_password_secret: str | None,
    digest_password_key: str,
    digest_realm: str | None,
    dry_run: bool,
    output: str,
) -> None:
    try:
        manifest = builders.sip_trunk(
            name=name,
            namespace=ctx.namespace,
            gateway=gateway,
            termination_uri=termination_uri,
            inbound_dial_policy=inbound_dial_policy,
            allowed_source_cidrs=allowed_source_cidr,
            caller_id_secret=caller_id_secret,
            caller_id_key=caller_id_key,
            authentication_mode=authentication_mode,
            digest_username_secret=digest_username_secret,
            digest_username_key=digest_username_key,
            digest_password_secret=digest_password_secret,
            digest_password_key=digest_password_key,
            digest_realm=digest_realm,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    emit_or_apply(ctx, manifest, dry_run=dry_run, output_format=output)


@cli.group()
def route() -> None:
    """Manage CallRoute resources."""


@route.command("create")
@click.argument("name")
@click.option("--gateway", required=True)
@click.option("--scope", required=True)
@click.option("--priority", type=int, required=True)
@click.option("--match", "called_number", required=True)
@click.option("--target-user")
@click.option("--target-trunk")
@click.option("--target-asterisk-pool")
@click.option("--target-extension")
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def route_create(
    ctx: Context,
    name: str,
    gateway: str,
    scope: str,
    priority: int,
    called_number: str,
    target_user: str | None,
    target_trunk: str | None,
    target_asterisk_pool: str | None,
    target_extension: str | None,
    dry_run: bool,
    output: str,
) -> None:
    try:
        manifest = builders.call_route(
            name=name,
            namespace=ctx.namespace,
            gateway=gateway,
            scope=scope,
            priority=priority,
            match=called_number,
            target_user=target_user,
            target_trunk=target_trunk,
            target_asterisk_pool=target_asterisk_pool,
            target_extension=target_extension,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    emit_or_apply(ctx, manifest, dry_run=dry_run, output_format=output)


@cli.group()
def scope() -> None:
    """Manage CallScope resources."""


@scope.command("create")
@click.argument("name")
@click.option("--gateway", required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def scope_create(ctx: Context, name: str, gateway: str, dry_run: bool, output: str) -> None:
    emit_or_apply(
        ctx,
        builders.call_scope(name=name, namespace=ctx.namespace, gateway=gateway),
        dry_run=dry_run,
        output_format=output,
    )


@cli.group()
def policy() -> None:
    """Manage DialPolicy resources."""


@policy.command("create")
@click.argument("name")
@click.option("--gateway", required=True)
@click.option("--scope", "scopes", multiple=True, required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def policy_create(ctx: Context, name: str, gateway: str, scopes: tuple[str, ...], dry_run: bool, output: str) -> None:
    emit_or_apply(
        ctx,
        builders.dial_policy(name=name, namespace=ctx.namespace, gateway=gateway, scopes=scopes),
        dry_run=dry_run,
        output_format=output,
    )


@cli.group()
def secret() -> None:
    """Create KubeVoIP-related Secret resources."""


def read_secret_value(*, from_stdin: bool, value_file: str | None) -> str:
    if from_stdin:
        return click.get_text_stream("stdin").read()
    if value_file:
        return Path(value_file).read_text()
    raise click.ClickException("use --from-stdin or --value-file")


@secret.command("sip-user")
@click.argument("name")
@click.option("--key", default="password", show_default=True)
@click.option("--from-stdin", is_flag=True)
@click.option("--value-file", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def secret_sip_user(
    ctx: Context, name: str, key: str, from_stdin: bool, value_file: str | None, dry_run: bool, output: str
) -> None:
    value = read_secret_value(from_stdin=from_stdin, value_file=value_file)
    emit_or_apply(
        ctx,
        builders.secret(name=name, namespace=ctx.namespace, key=key, value=value),
        dry_run=dry_run,
        output_format=output,
    )


@secret.command("caller-id")
@click.argument("name")
@click.option("--key", default="callerId", show_default=True)
@click.option("--from-stdin", is_flag=True)
@click.option("--value-file", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def secret_caller_id(
    ctx: Context, name: str, key: str, from_stdin: bool, value_file: str | None, dry_run: bool, output: str
) -> None:
    value = read_secret_value(from_stdin=from_stdin, value_file=value_file)
    emit_or_apply(
        ctx,
        builders.secret(name=name, namespace=ctx.namespace, key=key, value=value),
        dry_run=dry_run,
        output_format=output,
    )


@cli.command()
@pass_context
def status(ctx: Context) -> None:
    """Summarize KubeVoIP resources in a namespace."""
    rows: list[list[str]] = []
    for resource in ctx.resources():
        if resource.scope != "Namespaced":
            continue
        try:
            listed = kube.list_custom(
                group=resource.group,
                version=resource.version,
                plural=resource.plural,
                namespace=ctx.namespace,
                scope=resource.scope,
                kubeconfig=ctx.kubeconfig,
                context=ctx.kube_context,
            )
        except Exception:
            continue
        for item in listed.get("items", []):
            rows.append([resource.kind, item["metadata"]["name"], item.get("status", {}).get("phase", "-")])
    if ctx.output == "json":
        click.echo(render.json_dump([{"kind": row[0], "name": row[1], "phase": row[2]} for row in rows]), nl=False)
    else:
        click.echo(render.table(["Kind", "Name", "Phase"], rows), nl=False)


if __name__ == "__main__":
    cli()
