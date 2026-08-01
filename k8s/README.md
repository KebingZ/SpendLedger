# Kubernetes deployment

Version tags publish `ghcr.io/kebingz/spend-ledger` through the release workflow. Create
`spendledger-secrets` through a managed secret solution and run the migration Job before rolling
out the API and worker Deployments.

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f your-rendered-secret.yaml
kubectl apply -f k8s/migration-job.yaml
kubectl wait --for=condition=complete job/spendledger-migrate -n spendledger --timeout=120s
kubectl apply -f k8s/api.yaml -f k8s/worker.yaml -f k8s/resilience.yaml
```

`network-policy.yaml` is intentionally conservative and requires environment-specific egress rules
for DNS, PostgreSQL, and any downstream broker before use. A dedicated migration Job prevents every
API replica from racing to migrate the schema during startup.
