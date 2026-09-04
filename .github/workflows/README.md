# GitHub Actions Workflows

CI/CD pipelines. All deployments to AWS run through these - no manual deploys.

## Owner
Ismael

## Workflows
- `ci.yml` - runs on every PR (lint, tests, terraform validate, frontend build)
- `deploy-infra.yml` - runs on merge to `main` when `infrastructure/` changes
- `deploy-app.yml` - runs on merge to `main` when `backend/`, `agents/`, or `frontend/` changes

## Authentication
Uses OIDC with a GitHub Actions IAM role in the project AWS account. No long-lived credentials in secrets.
