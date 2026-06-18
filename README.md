# KubeVoIP CLI

Command-line tools for working with KubeVoIP Kubernetes resources.

The package is published as `kubevoip` and exposes the `kubevoip` command:

```bash
uvx kubevoip --help
uvx kubevoip api-resources
uvx kubevoip --schema-source cluster --namespace telephony init
```

The CLI discovers KubeVoIP API details from CRDs. By default it fetches the
latest published KubeVoIP platform release and caches the CRD schema locally.
You can also use a local CRD file or the CRDs installed in a Kubernetes cluster.

## Examples

Create a small platform with demo PostgreSQL and two SIP users:

```bash
kubevoip --schema-source cluster --namespace telephony init
```

Use an existing PostgreSQL database instead:

```bash
printf '%s' "$POSTGRES_PASSWORD" | kubevoip --schema-source cluster --namespace telephony init \
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

Create individual platform resources. Friendly create commands apply by default
after a Kubernetes server-side dry-run:

```bash
kubevoip --schema-source cluster --namespace telephony network-profile create public
kubevoip --schema-source cluster --namespace telephony media-relay create main --network-profile public
kubevoip --schema-source cluster --namespace telephony gateway create main \
  --database-secret postgres-app \
  --network-profile public \
  --media-relay main
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
