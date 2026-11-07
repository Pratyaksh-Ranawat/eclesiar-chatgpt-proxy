# Eclesiar API Proxy

A public HTTPS service that forwards read-only GET requests to the Eclesiar API. The upstream API key remains in Render environment variables and is never returned to callers.

## Deploy on Render

1. Open Render and choose **New + → Blueprint**.
2. Connect this repository: https://github.com/Pratyaksh-Ranawat/eclesiar-chatgpt-proxy
3. Deploy the Blueprint. It uses the free web-service plan in Singapore.
4. In the service's **Environment** settings, add:
   - `ECLESIAR_API_KEY`: a newly generated Eclesiar API key. Do not reuse a key previously pasted into a chat or committed to GitHub.
   - `PROXY_ACCESS_TOKEN`: a long, random secret (at least 32 characters).
5. Save and allow Render to redeploy.

## Use

Base URL: `https://YOUR-SERVICE.onrender.com`

Unauthenticated health check: `GET /health`

Authenticated API request: `GET /api/your/eclesiar/endpoint`

Header: `Authorization: Bearer YOUR_PROXY_ACCESS_TOKEN`

Query parameters are forwarded, e.g. `GET /api/your/endpoint?page=2`.
Interactive API documentation will be available at `/docs`.

## Security

- Only GET requests are accepted; this proxy cannot mutate game data.
- The upstream host is fixed to `https://tests-api.eclesiar.com`; callers cannot supply arbitrary URLs.
- Both secrets belong in Render environment variables, never in source control or public prompts.
- Render free services may sleep while idle and take a short time to wake.
