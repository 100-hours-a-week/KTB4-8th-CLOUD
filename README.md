# KeepGo V1 deployment

`compose.yaml` runs Nginx, Next.js, Spring Boot, FastAPI and MySQL on one
`linux/amd64` EC2 instance. The worker is intentionally absent: the BE CI does
not publish a worker image yet. Docker Compose health checks and
`scripts/deploy.sh` verify that all five services start before CD succeeds.

## Before the first deployment

1. Install Docker Compose 2.30 or newer, AWS CLI, Git, curl, Python 3 and
   `python3-yaml` on the EC2 instance. The EC2 instance role needs ECR pull
   permissions and SSM access. Clone this repository to `/opt/keepgo/cloud`.
2. Prepare `/opt/keepgo/tls/fullchain.pem` and `privkey.pem`, and mount the
   database data volume at `/opt/keepgo/data/mysql`. These host paths must
   exist before `docker compose up`.
3. Put the application DB password in
   `/opt/keepgo/runtime/database-password` and its root password in
   `/opt/keepgo/runtime/database-root-password`. Create
   `/opt/keepgo/runtime/backend.env` with at least `DB_PASSWORD`,
   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `VWORLD_API_KEY`. The
   `DB_PASSWORD` value must match `database-password`. Create
   `/opt/keepgo/runtime/ai.env` with `GOOGLE_API_KEY`,
   `NAVER_MAP_CLIENT_ID` and `NAVER_MAP_CLIENT_SECRET`. Use unquoted
   `KEY=value` lines: Compose `format: raw` passes quotes literally.
   Keep these files outside Git and restrict their permissions.
4. Publish the BE image to `keepgo-backend` and replace the BE placeholder
   in `deployment/production-manifest.yaml` with its 40-character commit SHA.
   The file already names the currently published FE/Nginx and AI image SHAs.
   FE and Nginx must use the same FE commit SHA.
5. Configure the Cloud repository's GitHub Actions variables
   `AWS_DEPLOY_ROLE_ARN` and `PRODUCTION_EC2_INSTANCE_ID`. The deploy role's
   OIDC trust must permit this Cloud repository's `production` environment,
   and its policy must allow SSM SendCommand/GetCommandInvocation for the
   target instance. Create and review the `production` environment in GitHub.

## Validate and deploy

`python scripts/validate-manifest.py --structure-only` checks the Compose
structure before the BE image exists. With every real image SHA in the
manifest, `python scripts/validate-manifest.py` checks the deploy inputs.
Both commands validate configuration only; `docker compose pull` verifies
that the image tags exist during deployment.

In GitHub Actions, select **Deploy production** on the reviewed Cloud branch.
Run with `execute=false` to validate configuration. Set `execute=true` to
send the deployment to EC2 through SSM. The EC2 command checks out that
Cloud commit, validates the manifest and runtime files, pulls images, then
runs `docker compose up --wait`. It fails if any container health check fails.
Read the SSM command output in the workflow log on failure.

For a manual EC2 deployment after checking out the intended Cloud commit:

```bash
cd /opt/keepgo/cloud
export AWS_ACCOUNT_ID=602601433533 AWS_REGION=ap-northeast-2
bash scripts/deploy.sh
```

The temporary FE/AI smoke Compose from earlier work must be stopped before
this full deployment because both Nginx instances bind host ports 80 and 443.

## Integration-test scope

The deployment verifies Nginx HTTP health, the Next.js root route, the AI
`/health` route, BE port 8080 and a MySQL query. It also checks the
Nginx-to-FE and BE-to-AI/DB container network paths. BE's port check is temporary
until it provides an HTTP readiness endpoint. These checks do not prove that
Google OAuth, protected BE APIs or AI model requests work; exercise those
flows separately in the integration test.

The currently published FE image uses `/api` and a mock OAuth screen while
the BE login endpoint is `/api/v1/user/auth-session`. FE and BE developers
must align this contract and publish new images before login E2E can pass.
The FE's public Naver Maps client ID is also baked into the image at build
time; adding it to an EC2 env file does not update the current FE image.

On the current `t3.medium` (4 GiB RAM), the five memory limits total 3.375
GiB, leaving some space for the host. Monitor `free -h` and `docker stats`
during E2E traffic. Chroma remains inside the AI container for this V1
deployment; its derived index is lost when the AI container is replaced and
must be rebuilt from the source data.
