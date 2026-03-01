# YouTube Monitor — Google Cloud Deployment Guide

> **Important caveat before you start:** YouTube blocks transcript and audio downloads from GCP IP addresses. Cloud deployment is only viable if transcript-based analysis (for channels that provide captions) is sufficient. For full audio analysis, run the tool locally instead — see the README.

## Step 1: Install the Google Cloud CLI

1. Download the installer: [Google Cloud SDK for Windows](https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe)
2. Run it and follow the prompts (defaults are fine)
3. At the end, **close and reopen PowerShell** so `gcloud` is on your PATH
4. Verify it works:
```powershell
gcloud version
```

## Step 2: Create a GCP Project and Log In

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project
2. Note your **Project ID** (e.g. `youtube-monitor-12345`) — you'll use it throughout these steps

```powershell
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

## Step 3: Enable Required APIs

```powershell
gcloud services enable cloudfunctions.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com storage.googleapis.com run.googleapis.com
```

## Step 4: Create a Storage Bucket (for your database)

```powershell
gcloud storage buckets create gs://YOUR_PROJECT_ID-data --location=us-central1
```

## Step 5: Push Your Secrets

Create each secret (replace the values with your actual credentials from `.env`):

```powershell
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=-
echo -n "YOUR_GMAIL_ADDRESS" | gcloud secrets create gmail-address --data-file=-
echo -n "YOUR_GMAIL_APP_PASSWORD" | gcloud secrets create gmail-app-password --data-file=-
echo -n "YOUR_REPORT_RECIPIENT_EMAIL" | gcloud secrets create report-recipient --data-file=-
```

Now push your YouTube cookies as a secret:

```powershell
gcloud secrets create youtube-cookies --data-file="www.youtube.com_cookies.json"
```

## Step 6: Deploy the Cloud Function

```powershell
cd path/to/youtube-monitor

gcloud functions deploy youtube-monitor --gen2 --runtime=python312 --region=us-central1 --source=. --entry-point=cloud_entry --trigger-http --memory=512MiB --timeout=540s --set-env-vars="GCS_BUCKET=YOUR_PROJECT_ID-data,GCP_PROJECT=YOUR_PROJECT_ID" --no-allow-unauthenticated
```

> First deploy takes 3–5 minutes while it builds the container. Subsequent deploys are faster.

After deployment, note the **Function URL** it prints.

## Step 7: Grant the Function Access to Secrets

```powershell
# Get the service account email
gcloud functions describe youtube-monitor --gen2 --region=us-central1 --format="value(serviceConfig.serviceAccountEmail)"
```

Copy the email it prints, then grant it access:

```powershell
# Replace SERVICE_ACCOUNT_EMAIL with the email from above
gcloud projects add-iam-member --project=YOUR_PROJECT_ID --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-member --project=YOUR_PROJECT_ID --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" --role="roles/storage.objectAdmin"
```

## Step 8: Test It Manually

```powershell
gcloud functions call youtube-monitor --gen2 --region=us-central1
```

Check your email — you should get the report.

## Step 9: Set Up the Daily Schedule

```powershell
# Get the function URL
gcloud functions describe youtube-monitor --gen2 --region=us-central1 --format="value(serviceConfig.uri)"
```

Then create the scheduler job (replace FUNCTION_URL and SERVICE_ACCOUNT_EMAIL):

```powershell
gcloud scheduler jobs create http youtube-daily-audit --location=us-central1 --schedule="0 4 * * *" --time-zone="America/Chicago" --uri="FUNCTION_URL" --http-method=POST --oidc-service-account-email="SERVICE_ACCOUNT_EMAIL"
```

**Done!** The function will now run every day at 4:00 AM Central Time.

---

## Maintenance

### When Cookies Expire (every few months)
1. Re-export cookies from Chrome using the Cookie-Editor extension
2. Update the secret:
```powershell
gcloud secrets versions add youtube-cookies --data-file="www.youtube.com_cookies.json"
```

### View Logs
```powershell
gcloud functions logs read youtube-monitor --gen2 --region=us-central1 --limit=50
```

### Redeploy After Code Changes
```powershell
cd path/to/youtube-monitor
gcloud functions deploy youtube-monitor --gen2 --runtime=python312 --region=us-central1 --source=. --entry-point=cloud_entry --trigger-http --memory=512MiB --timeout=540s --set-env-vars="GCS_BUCKET=YOUR_PROJECT_ID-data,GCP_PROJECT=YOUR_PROJECT_ID" --no-allow-unauthenticated
```

---

## Cloud Execution Time Limit

Google Cloud Functions have a 9-minute maximum execution time. To handle this safely:

- `main.py` tracks elapsed time and stops enrichment/classification at 7.5 minutes
- Any analyzed videos are reported and saved before the function exits
- Unanalyzed videos stay in the database and are processed on the next run

This prevents data loss if a large backlog of new videos is encountered.
