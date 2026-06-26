# KubeVoIP CLI

A CLI for creating and inspecting KubeVoIP Kubernetes resources.

The package is published as `kubevoip` and exposes the `kubevoip` command:

```bash
uvx kubevoip --help
uvx kubevoip api-resources
uvx kubevoip --namespace telephony operator install --version X.Y.Z --create-namespace
uvx kubevoip --namespace telephony init
```

The CLI discovers KubeVoIP API details from CRDs. By default it uses the
installed cluster CRDs for live commands such as `init`, `get`, and `apply`,
and uses the latest published KubeVoIP release for offline commands such as
`manifest` and `explain`. You can override this with `--schema-source
latest|cluster|file`.

## Examples

Install or upgrade the KubeVoIP operator with the standard Helm repository:

```bash
kubevoip --namespace telephony operator install \
  --version X.Y.Z \
  --create-namespace
```

The install command wraps Helm and installs only the operator chart. Use
`kubevoip init` after installation to create a demo database, SIP gateway,
media relay, users, policies, and routes. Platform image releases can appear
before the matching chart release because chart publication follows a reviewed
release step.

Create a small platform with demo PostgreSQL and two SIP users:

```bash
kubevoip --namespace telephony init
```

Use an existing PostgreSQL database instead:

```bash
printf '%s' "$POSTGRES_PASSWORD" | kubevoip --namespace telephony init \
  --database existing \
  --postgres-host "$POSTGRES_HOST" \
  --postgres-db kubevoip \
  --postgres-user kubevoip \
  --postgres-password-stdin
```

Generate a manifest:

```bash
kubevoip manifest sipuser --name alice --namespace telephony
```

Create individual platform resources. Resource-specific create commands apply by
default after a Kubernetes server-side dry-run:

```bash
kubevoip --namespace telephony network-profile create public
kubevoip --namespace telephony media-relay create main --network-profile public
kubevoip --namespace telephony gateway create main \
  --database-secret postgres-app \
  --network-profile public \
  --media-relay main \
  --sip-headers \
  --sdp
kubevoip user create alice \
  --extension 100 \
  --gateway main \
  --dial-policy internal-external \
  --auth-username alice \
  --caller-id "Alice <100>" \
  --password-secret alice-sip \
  --namespace telephony
```

Print GitOps-friendly YAML instead:

```bash
kubevoip user create alice \
  --extension 100 \
  --gateway main \
  --dial-policy internal-external \
  --auth-username alice \
  --password-secret alice-sip \
  --namespace telephony \
  --dry-run -o yaml
```

Update a user's extension without re-entering the rest of the SIPUser spec. The
CLI reads the live resource, merges the changed fields, then applies the result:

```bash
kubevoip user update alice \
  --extension 101 \
  --caller-id "Alice <101>" \
  --namespace telephony
```

Create a SIP user Secret without putting the value in shell history:

```bash
printf '%s' "$SIP_PASSWORD" | kubevoip secret sip-user alice-sip \
  --namespace telephony \
  --from-stdin
```

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv run kubevoip --help
```
