// Stands in for Supabase Auth in the end-to-end tests: it signs in each handler in
// data/handlers.json with the password in HANDLER_PASSWORD, signing their token
// with an ES256 key of its own, serves the public key the backend checks tokens
// with, and answers the browser's cross-origin checks.
import { generateKeyPairSync, randomUUID, sign } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer, type ServerResponse } from "node:http";
import { json } from "node:stream/consumers";

const KEY_ID = "e2e-key";
const LIFETIME = 3600;
const handlers = JSON.parse(readFileSync("data/handlers.json", "utf8")) as {
  email: string;
}[];
const { privateKey, publicKey } = generateKeyPairSync("ec", {
  namedCurve: "P-256",
});
const publicJwk = {
  ...publicKey.export({ format: "jwk" }),
  kid: KEY_ID,
  alg: "ES256",
  use: "sig",
};

const base64url = (data: string | Buffer) =>
  Buffer.from(data).toString("base64url");

function token(email: string, expiresAt: number): string {
  const header = base64url(
    JSON.stringify({ alg: "ES256", typ: "JWT", kid: KEY_ID }),
  );
  const claims = {
    sub: email,
    email,
    aud: "authenticated",
    iss: `http://127.0.0.1:${String(process.env.PORT)}/auth/v1`,
    exp: expiresAt,
  };
  const signed = `${header}.${base64url(JSON.stringify(claims))}`;
  const signature = sign("sha256", Buffer.from(signed), {
    key: privateKey,
    dsaEncoding: "ieee-p1363",
  });
  return `${signed}.${base64url(signature)}`;
}

function reply(response: ServerResponse, status: number, body?: unknown) {
  response.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  });
  response.end(body === undefined ? undefined : JSON.stringify(body));
}

function session(email: string) {
  const expiresAt = Math.floor(Date.now() / 1000) + LIFETIME;
  return {
    access_token: token(email, expiresAt),
    refresh_token: randomUUID(),
    token_type: "bearer",
    expires_in: LIFETIME,
    expires_at: expiresAt,
    user: {
      id: email,
      aud: "authenticated",
      email,
      app_metadata: {},
      user_metadata: {},
      created_at: "2026-10-01T00:00:00Z",
    },
  };
}

createServer((request, response) => {
  const url = request.url ?? "";
  if (request.method === "OPTIONS") {
    reply(response, 204);
  } else if (url === "/auth/v1/.well-known/jwks.json") {
    reply(response, 200, { keys: [publicJwk] });
  } else if (
    request.method === "POST" &&
    url === "/auth/v1/token?grant_type=password"
  ) {
    json(request).then(
      (body) => {
        const { email, password } = body as { email: string; password: string };
        const known = handlers.some((handler) => handler.email === email);
        if (known && password === process.env.HANDLER_PASSWORD)
          reply(response, 200, session(email));
        else
          reply(response, 400, {
            error: "invalid_grant",
            error_description: "Invalid login credentials",
          });
      },
      () => {
        reply(response, 400, { error: "invalid_request" });
      },
    );
  } else if (url === "/health") {
    reply(response, 200, { status: "ok" });
  } else {
    reply(response, 404, { error: "not_found" });
  }
}).listen(Number(process.env.PORT), "127.0.0.1");
