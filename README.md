# KubeVoIP CLI

Command-line tools for working with KubeVoIP Kubernetes resources.

The package is published as `kubevoip` and exposes the `kubevoip` command:

```bash
uvx kubevoip --help
uvx kubevoip api-resources
uvx kubevoip manifest sipuser --name alice --namespace telephony
```

The CLI discovers KubeVoIP API details from CRDs. By default it fetches the
latest published KubeVoIP platform release and caches the CRD schema locally.
You can also use a local CRD file or the CRDs installed in a Kubernetes cluster.

## Examples

Generate a manifest:

```bash
kubevoip manifest sipuser --name alice --namespace telephony
```

Create a user. Friendly create commands apply by default after a Kubernetes
server-side dry-run:

```bash
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

