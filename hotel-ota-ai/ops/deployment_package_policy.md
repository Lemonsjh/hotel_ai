# Deployment Package Policy

1. The repository is not the deployment package.
2. The deployment package contains only runtime-required files.
3. Development audits, plans, legacy diagrams, PR drafts, and test files do not enter the deployment package.
4. Source documents are collaboration references and are not required in the deployment package.
5. Private config belongs in `/etc/hotel-ota-ai/` or server environment variables.
6. `.env`, role maps, database mappings, and secrets must never enter the repository or package.
7. Demo data is used only by Demo Mode and must never allow formal approval or live execution.
8. Server updates require backup, dry-run verification, and rollback readiness.
9. `manifests/deploy_manifest.yaml` is the source of truth for deployment boundaries.
