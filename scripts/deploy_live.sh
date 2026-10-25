#!/usr/bin/env bash
# Live deploy for the sandbox-blocked targets (phase 7).
# The sandbox proxy cannot reach firebaserules/hosting/functions/run APIs,
# so run this from a normal shell after `firebase login`.
# Firestore indexes are deployed separately (reachable from anywhere).
set -euo pipefail

PROJECT="${1:-tinder-jobs-4bf1b}"
REGION="${REGION:-europe-west1}"

if [ "$PROJECT" = "tinder-jobs-4bf1b" ]; then
  echo "Legacy compute retired on 2026-10-05. Deploy retained Hosting separately." >&2
  exit 1
fi

echo "== $PROJECT: Firestore rules (needs firebaserules API) =="
firebase deploy --only firestore:rules --project "$PROJECT"

echo "== $PROJECT: Hosting (PWA) =="
firebase deploy --only hosting --project "$PROJECT"

echo "== $PROJECT: Cloud Functions (Python, source=root) =="
firebase deploy --only functions --project "$PROJECT"

echo "== $PROJECT: latex-worker image + Cloud Run =="
gcloud artifacts repositories create jaa-workers --repository-format=docker \
  --location="$REGION" --project="$PROJECT" 2>/dev/null || true
gcloud builds submit --config=deploy/cloudbuild-latex.yaml \
  --substitutions=_REGION="$REGION" --project="$PROJECT"
sed -e "s/REGION/$REGION/g" -e "s/PROJECT_ID/$PROJECT/g" \
  deploy/cloudrun-latex.yaml > /tmp/cloudrun-latex.resolved.yaml
gcloud run services replace /tmp/cloudrun-latex.resolved.yaml \
  --region="$REGION" --project="$PROJECT"

echo "LIVE DEPLOY DONE for $PROJECT"
