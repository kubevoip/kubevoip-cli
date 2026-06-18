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


def emit_or_apply_many(
    ctx: Context, manifests: list[dict[str, Any]], *, dry_run: bool, output_format: str
) -> None:
    if dry_run:
        click.echo(render.output(manifests, fmt="json" if output_format == "json" else "yaml"), nl=False)
        return
    applied = 0
    for manifest in manifests:
        try:
            resource = None
            if manifest.get("apiVersion", "").startswith("kubevoip.com/"):
                resource = ctx.resource(manifest["kind"])
            kube.apply_manifest(
                manifest,
                resource=resource,
                namespace=ctx.namespace,
                kubeconfig=ctx.kubeconfig,
                context=ctx.kube_context,
            )
            applied += 1
        except Exception as exc:
            kind = manifest.get("kind", "resource")
            name = manifest.get("metadata", {}).get("name", "<unknown>")
            raise click.ClickException(f"failed to apply {kind}/{name}: {exc}") from exc
    click.echo(render.output({"applied": applied}, fmt="json" if output_format == "json" else "yaml"), nl=False)


@cli.group()
def quickstart() -> None:
    """Create optional quickstart support resources."""


@quickstart.command("postgres")
@click.option("--postgres-name", default="postgres", show_default=True)
@click.option("--postgres-secret", default="postgres-app", show_default=True)
@click.option("--database", default="kubevoip", show_default=True)
@click.option("--database-user", default="kubevoip", show_default=True)
@click.option("--database-password", default="kubevoip-demo-password", show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def quickstart_postgres(
    ctx: Context,
    postgres_name: str,
    postgres_secret: str,
    database: str,
    database_user: str,
    database_password: str,
    dry_run: bool,
    output: str,
) -> None:
    """Create a demo PostgreSQL Deployment, Service, and connection Secret."""
    if not ctx.namespace:
        raise click.ClickException("--namespace is required")
    manifests = builders.demo_postgres(
        namespace=ctx.namespace,
        postgres_name=postgres_name,
        postgres_secret=postgres_secret,
        database=database,
        database_user=database_user,
        database_password=database_password,
    )
    emit_or_apply_many(ctx, manifests, dry_run=dry_run, output_format=output)


@cli.command()
@click.option("--gateway", default="main", show_default=True)
@click.option("--network-profile", default="public", show_default=True)
@click.option("--media-relay", default="main", show_default=True)
@click.option("--database", "database_mode", type=click.Choice(["demo", "existing"]), default="demo", show_default=True)
@click.option("--database-secret", default="postgres-app", show_default=True)
@click.option("--postgres-name", default="postgres", show_default=True)
@click.option("--postgres-db", default="kubevoip", show_default=True)
@click.option("--postgres-user", default="kubevoip", show_default=True)
@click.option("--postgres-password", default="kubevoip-demo-password", show_default=True)
@click.option("--postgres-host")
@click.option("--postgres-port", default="5432", show_default=True)
@click.option("--postgres-password-stdin", is_flag=True)
@click.option("--postgres-password-file", type=click.Path(exists=True, dir_okay=False))
@click.option("--two-phones/--no-two-phones", default=True, show_default=True)
@click.option("--alice-password", default="alice-demo-password", show_default=True)
@click.option("--bob-password", default="bob-demo-password", show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def init(
    ctx: Context,
    gateway: str,
    network_profile: str,
    media_relay: str,
    database_mode: str,
    database_secret: str,
    postgres_name: str,
    postgres_db: str,
    postgres_user: str,
    postgres_password: str,
    postgres_host: str | None,
    postgres_port: str,
    postgres_password_stdin: bool,
    postgres_password_file: str | None,
    two_phones: bool,
    alice_password: str,
    bob_password: str,
    dry_run: bool,
    output: str,
) -> None:
    """Create a minimal KubeVoIP platform, optionally with two demo phones."""
    if not ctx.namespace:
        raise click.ClickException("--namespace is required")

    manifests: list[dict[str, Any]] = []
    if database_mode == "demo":
        manifests.extend(
            builders.demo_postgres(
                namespace=ctx.namespace,
                postgres_name=postgres_name,
                postgres_secret=database_secret,
                database=postgres_db,
                database_user=postgres_user,
                database_password=postgres_password,
            )
        )
    elif postgres_host or postgres_password_stdin or postgres_password_file:
        if not postgres_host:
            raise click.ClickException("--postgres-host is required when creating a database Secret")
        password = read_secret_value(from_stdin=postgres_password_stdin, value_file=postgres_password_file)
        manifests.append(
            builders.database_secret(
                name=database_secret,
                namespace=ctx.namespace,
                host=postgres_host,
                port=postgres_port,
                database=postgres_db,
                username=postgres_user,
                password=password,
            )
        )

    manifests.extend(
        builders.init_platform(
            namespace=ctx.namespace,
            gateway=gateway,
            network_profile_name=network_profile,
            media_relay_name=media_relay,
            database_secret_name=database_secret,
        )
    )

    if two_phones:
        manifests.extend(
            builders.two_phone_resources(
                namespace=ctx.namespace,
                gateway=gateway,
                alice_password=alice_password,
                bob_password=bob_password,
            )
        )

    emit_or_apply_many(ctx, manifests, dry_run=dry_run, output_format=output)


@cli.group("network-profile")
def network_profile() -> None:
    """Manage NetworkProfile resources."""


@network_profile.command("create")
@click.argument("name")
@click.option("--local-network", multiple=True, default=("10.0.0.0/8",), show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def network_profile_create(
    ctx: Context, name: str, local_network: tuple[str, ...], dry_run: bool, output: str
) -> None:
    emit_or_apply(
        ctx,
        builders.network_profile(name=name, namespace=ctx.namespace, local_networks=local_network),
        dry_run=dry_run,
        output_format=output,
    )


@cli.group("media-relay")
def media_relay() -> None:
    """Manage MediaRelay resources."""


@media_relay.command("create")
@click.argument("name")
@click.option("--network-profile", required=True)
@click.option("--rtp-start", type=int, default=20000, show_default=True)
@click.option("--rtp-end", type=int, default=20049, show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def media_relay_create(
    ctx: Context,
    name: str,
    network_profile: str,
    rtp_start: int,
    rtp_end: int,
    dry_run: bool,
    output: str,
) -> None:
    emit_or_apply(
        ctx,
        builders.media_relay(
            name=name,
            namespace=ctx.namespace,
            network_profile_name=network_profile,
            rtp_start=rtp_start,
            rtp_end=rtp_end,
        ),
        dry_run=dry_run,
        output_format=output,
    )


@cli.group()
def gateway() -> None:
    """Manage SIPGateway resources."""


@gateway.command("create")
@click.argument("name")
@click.option("--database-secret", required=True)
@click.option("--network-profile", required=True)
@click.option("--media-relay", required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def gateway_create(
    ctx: Context,
    name: str,
    database_secret: str,
    network_profile: str,
    media_relay: str,
    dry_run: bool,
    output: str,
) -> None:
    emit_or_apply(
        ctx,
        builders.sip_gateway(
            name=name,
            namespace=ctx.namespace,
            database_secret=database_secret,
            network_profile_name=network_profile,
            media_relay_name=media_relay,
        ),
        dry_run=dry_run,
        output_format=output,
    )


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


@secret.command("database")
@click.argument("name")
@click.option("--host", required=True)
@click.option("--port", default="5432", show_default=True)
@click.option("--dbname", required=True)
@click.option("--user", "database_user", required=True)
@click.option("--password-stdin", is_flag=True)
@click.option("--password-file", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True)
@click.option("--output", "-o", type=click.Choice(["yaml", "json"]), default="yaml")
@pass_context
def secret_database(
    ctx: Context,
    name: str,
    host: str,
    port: str,
    dbname: str,
    database_user: str,
    password_stdin: bool,
    password_file: str | None,
    dry_run: bool,
    output: str,
) -> None:
    password = read_secret_value(from_stdin=password_stdin, value_file=password_file)
    emit_or_apply(
        ctx,
        builders.database_secret(
            name=name,
            namespace=ctx.namespace,
            host=host,
            port=port,
            database=dbname,
            username=database_user,
            password=password,
        ),
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
