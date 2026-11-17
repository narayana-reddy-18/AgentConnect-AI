import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, api } from "../src/api.js";

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("auth and protected API requests send cookies and CSRF tokens", async (t) => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  api.setCsrfToken(null);
  t.after(() => {
    globalThis.fetch = originalFetch;
    api.setCsrfToken(null);
  });

  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith("/auth/session")) {
      return jsonResponse({
        id: 8,
        email: "signed-in@example.com",
        email_verified: true,
        name: "Signed In",
      });
    }
    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "test-csrf-token" });
    }
    if (url.endsWith("/agents")) {
      return jsonResponse({ id: 3 });
    }
    if (url.endsWith("/agents/mine")) {
      return jsonResponse([{ id: 3 }]);
    }
    if (url.endsWith("/auth/logout")) {
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected request: ${url}`);
  };

  const user = await api.getSession();
  assert.equal(user.email, "signed-in@example.com");
  api.setCsrfToken(await api.getCsrfToken());
  assert.deepEqual(await api.listMyAgents(), [{ id: 3 }]);
  await api.registerAgent({ name: "Agent", email: "agent@example.com" });
  await api.logout();

  assert.ok(requests.every(({ options }) => options.credentials === "include"));
  const registerRequest = requests.find(({ url }) => url.endsWith("/agents"));
  assert.equal(
    registerRequest.options.headers["X-CSRF-Token"],
    "test-csrf-token",
  );
  const logoutRequest = requests.find(({ url }) => url.endsWith("/auth/logout"));
  assert.equal(logoutRequest.options.headers["X-CSRF-Token"], "test-csrf-token");
  assert.equal(api.googleLoginUrl, "/api/v1/auth/google/login");
});

test("mutating API requests are blocked until a CSRF token is set", async (t) => {
  const originalFetch = globalThis.fetch;
  api.setCsrfToken(null);
  t.after(() => {
    globalThis.fetch = originalFetch;
    api.setCsrfToken(null);
  });

  let fetchCalled = false;
  globalThis.fetch = async () => {
    fetchCalled = true;
    return jsonResponse({});
  };

  await assert.rejects(
    api.createPost({ agent_id: 1, content: "Test" }),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 403);
      return true;
    },
  );
  assert.equal(fetchCalled, false);
});

test("API errors preserve HTTP status for expired-session handling", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = async () =>
    jsonResponse({ detail: "Authentication required" }, 401);

  await assert.rejects(api.getSession(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 401);
    assert.equal(error.message, "Authentication required");
    return true;
  });
});
