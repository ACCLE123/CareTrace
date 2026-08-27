# CareTrace frontend (Next.js + Vercel)

This folder is a standalone **Next.js 15 + TypeScript** frontend. It has no server-side permissions or patient data logic; all access control remains in the FastAPI API.

## Deploy to Vercel

1. Import this repository in Vercel and set **Root Directory** to `frontend`.
2. Vercel detects **Next.js** automatically.
3. Add a Vercel environment variable named `NEXT_PUBLIC_API_BASE_URL`, such as `https://api.example.com` (no trailing slash), then deploy.
4. Set the backend's `CORS_ORIGINS` environment variable to the exact Vercel URL, for example `https://caretrace.vercel.app`, then restart/redeploy the backend.

`NEXT_PUBLIC_API_BASE_URL` is public client configuration, so it must never contain database URLs, tokens, or secrets.
