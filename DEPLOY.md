# Deployment Playbook

Merging to `main` deploys automatically via GitHub Actions:

| Path changed | Workflow | Deploys to |
|---|---|---|
| `backend/**` | `.github/workflows/backend.yml` | Cloud Run |
| `frontend/**` | `.github/workflows/frontend.yml` | Firebase Hosting |

Monitor runs at: `https://github.com/yuanwang688/todo_app/actions`

---

## Database migrations

Migrations are **not** run by CI/CD — run them manually before deploying a backend change that requires them:

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

---

## Manual deployment

Use these when you need to deploy outside of CI/CD (e.g. hotfix, secret rotation).

All commands assume:
```bash
export PATH="/home/yuan/.nvm/versions/node/v18.20.8/bin:/home/yuan/google-cloud-sdk/bin:$PATH"
```

### Backend

```bash
# Run from repo root
sg docker -c "docker build -t us-central1-docker.pkg.dev/todo-app-yw688/todo-backend/app:latest backend/"
sg docker -c "docker push us-central1-docker.pkg.dev/todo-app-yw688/todo-backend/app:latest"

gcloud run deploy todo-backend \
  --image us-central1-docker.pkg.dev/todo-app-yw688/todo-backend/app:latest \
  --region us-central1 \
  --project todo-app-yw688
```

### Frontend

```bash
cd frontend
npm run build
firebase deploy --only hosting
```

---

## Rotating a secret

Add a new secret version, then redeploy Cloud Run to pick it up:

```bash
echo -n "NEW_VALUE" | gcloud secrets versions add SECRET_NAME \
  --data-file=- --project=todo-app-yw688

# Then redeploy (Cloud Run pulls latest secret version on each new revision)
gcloud run deploy todo-backend \
  --image us-central1-docker.pkg.dev/todo-app-yw688/todo-backend/app:latest \
  --region us-central1 \
  --project todo-app-yw688
```

---

## Verifying a deployment

```bash
# Backend health
curl https://todo-app-yw688.web.app/api/health
# Expected: {"status":"ok"}

# Check active Cloud Run revision
gcloud run revisions list --service=todo-backend --region=us-central1 --project=todo-app-yw688
```
