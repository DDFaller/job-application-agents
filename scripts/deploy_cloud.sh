#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Full Cloud Deployment Script for Job Application Agents
# The project must be supplied by the caller; this script has no user default.
# ==============================================================================

PROJECT_ID="${JAA_FIREBASE_PROJECT_ID:?Set JAA_FIREBASE_PROJECT_ID to your Firebase project}"
REGION="${GCP_REGION:-europe-west1}"
NOTION_DB_ID="${NOTION_DATABASE_ID:-3c7ac433-f81d-80bd-959d-ecfeba5f8ffe}"
ENABLE_SUBMISSION=false
if [ "${1:-}" = "--enable-submission" ]; then
    ENABLE_SUBMISSION=true
    if [ "${JAA_ENABLE_SUBMISSION:-}" != "I_UNDERSTAND_SUBMISSION" ]; then
        echo "Refusing submission-worker deployment: set JAA_ENABLE_SUBMISSION=I_UNDERSTAND_SUBMISSION explicitly." >&2
        exit 1
    fi
fi

echo "=================================================================="
echo "🚀 DEPLOYING JOB APPLICATION AGENTS TO FULL CLOUD (GCP & FIREBASE)"
echo "=================================================================="
echo "Project ID:          $PROJECT_ID"
echo "Cloud Region:        $REGION"
echo "Notion Database ID:  $NOTION_DB_ID"
echo "=================================================================="

# 1. Deploy Firestore Security Rules & Indexes
echo -e "\n[1/4] Deploying Firestore Security Rules & Indexes..."
npx firebase-tools deploy --only firestore --project "$PROJECT_ID" || {
    echo "Warning: Firebase CLI rules deploy skipped or requires login."
}

# 2. Deploy Mobile Review PWA to Firebase Hosting
echo -e "\n[2/4] Deploying Mobile Review PWA to Firebase Hosting..."
npx firebase-tools deploy --only hosting --project "$PROJECT_ID" || {
    echo "Warning: Firebase Hosting deploy skipped or requires login."
}

# 3. Build Container Images via Cloud Build
echo -e "\n[3/4] Building container images with Google Cloud Build (deploy/cloudbuild.yaml)..."
gcloud builds submit --config deploy/cloudbuild.yaml --project "$PROJECT_ID" .

# 4. Deploy Cloud Run Worker Daemons
echo -e "\n[4/4] Deploying Cloud Run Worker Services..."

# A. Deploy Playwright Submission Worker only by explicit opt-in.
if [ "$ENABLE_SUBMISSION" = true ]; then
    echo " -> Deploying jaa-playwright-worker (explicit submission opt-in)..."
    gcloud run deploy jaa-playwright-worker \
        --image "gcr.io/$PROJECT_ID/playwright-worker" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --platform managed \
        --memory 1Gi \
        --cpu 1 \
        --min-instances 1 \
        --max-instances 1 \
        --set-env-vars "JAA_FIREBASE_PROJECT_ID=$PROJECT_ID,GCLOUD_PROJECT=$PROJECT_ID,JAA_ENABLE_SUBMISSION=I_UNDERSTAND_SUBMISSION" \
        --no-allow-unauthenticated
else
    echo " -> Skipping jaa-playwright-worker (submission disabled by default)."
fi

# B. Deploy Notion Sync Worker
echo " -> Deploying jaa-notion-worker..."
gcloud run deploy jaa-notion-worker \
    --image "gcr.io/$PROJECT_ID/notion-worker" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --platform managed \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 1 \
    --max-instances 1 \
    --set-env-vars "JAA_FIREBASE_PROJECT_ID=$PROJECT_ID,NOTION_DATABASE_ID=$NOTION_DB_ID,GCLOUD_PROJECT=$PROJECT_ID" \
    --no-allow-unauthenticated

# C. Deploy LaTeX Render Worker
echo " -> Deploying jaa-latex-worker..."
gcloud run deploy jaa-latex-worker \
    --image "gcr.io/$PROJECT_ID/latex-worker" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --platform managed \
    --memory 1Gi \
    --cpu 1 \
    --min-instances 1 \
    --max-instances 1 \
    --set-env-vars "JAA_FIREBASE_PROJECT_ID=$PROJECT_ID,JAA_ARTIFACT_ROOT=/artifacts,GCLOUD_PROJECT=$PROJECT_ID" \
    --no-allow-unauthenticated


echo -e "\n=================================================================="
echo "✅ FULL CLOUD DEPLOYMENT COMPLETED"
echo "=================================================================="
echo "📱 Mobile Review PWA:   https://$PROJECT_ID.web.app"
echo "🗄️ Firestore Database:   https://console.firebase.google.com/project/$PROJECT_ID/firestore"
echo "🤖 Cloud Run Services:  https://console.cloud.google.com/run?project=$PROJECT_ID"
echo "=================================================================="
