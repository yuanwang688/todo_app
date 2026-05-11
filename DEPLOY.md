# Deployment Playbook

## Prerequisites

All commands below assume these are on your `PATH`:
```bash
export PATH="/home/yuan/.nvm/versions/node/v18.20.8/bin:/home/yuan/google-cloud-sdk/bin:$PATH"
```

---

## Backend

Any change under `backend/app/` requires rebuilding and pushing the Docker image, then redeploying Cloud Run.

```bash
# 1. Build image (run from repo root)
sg docker -c "docker build -t us-central1-docker.pkg.dev/todo-app-yw688/todo-backend/app:latest backend/"

# 2. Push to Artifact Registry
sg docker -c "docker push us-central1-docker.pkg.dev/todo-app-yw688/todo-backend/app:latest"

# 3. Deploy new revision to Cloud Run
gcloud run deploy todo-backend \
  --image us-central1-docker.pkg.dev/todo-app-yw688/todo-backend/app:latest \
  --region us-central1 \
  --project todo-app-yw688
```

If the change includes a new Alembic migration, run it against the production database before or after deploying (the migration is backward-compatible if you run it first):

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

---

## Frontend

Any change under `frontend/src/` requires rebuilding and redeploying to Firebase Hosting.

```bash
cd frontend

# 1. Build
npm run build

# 2. Deploy
firebase deploy --only hosting
```

The built files in `dist/` are what gets deployed. The Firebase rewrite rules in `firebase.json` forward `/api/**` and `/auth/**` to Cloud Run automatically — no changes needed there for typical frontend updates.

---

## Updating secrets

To rotate a secret (e.g. `JWT_SECRET`), add a new version in Secret Manager then redeploy Cloud Run to pick it up:

```bash
echo -n "NEW_VALUE" | gcloud secrets versions add SECRET_NAME \
  --data-file=- --project=todo-app-yw688

# Then redeploy as above (step 3) — Cloud Run pulls latest secret version on each new revision
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
