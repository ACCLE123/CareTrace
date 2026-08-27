# CareTrace frontend (Vercel)

This folder is a standalone static frontend. It has no server-side permissions or patient data logic; all access control remains in the FastAPI API.

## Deploy to Vercel

1. Import this repository in Vercel and set **Root Directory** to `frontend`.
2. Add a Vercel environment variable named `CARETRACE_API_BASE_URL`, such as `https://api.example.com` (no trailing slash), then deploy.
3. Vercel serves the value through `/api/runtime-config`; it is public browser configuration, not a secret.
4. Set the backend's `CORS_ORIGINS` environment variable to the exact Vercel URL, for example `https://caretrace.vercel.app`, then restart/redeploy the backend.

`CARETRACE_API_BASE_URL` is public client configuration, so it must never contain database URLs, tokens, or secrets.
