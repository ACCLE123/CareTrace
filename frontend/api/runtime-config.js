export default function handler(_request, response) {
  const apiBaseUrl = (process.env.CARETRACE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
  response.setHeader("Content-Type", "application/javascript; charset=utf-8");
  response.setHeader("Cache-Control", "no-store");
  response.status(200).send(`window.CARETRACE_API_BASE_URL = ${JSON.stringify(apiBaseUrl)};`);
}
