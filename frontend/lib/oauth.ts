/**
 * PKCE (Proof Key for Code Exchange) helpers for OAuth2 authorization flows.
 *
 * Usage
 * -----
 * 1. Generate a `code_verifier` and store it in `sessionStorage`.
 * 2. Compute the `code_challenge` and send it to the backend authorize endpoint.
 * 3. After the provider redirects back, read the verifier from storage and
 *    include it in the callback request body.
 *
 * The verifier never leaves the browser — only its SHA-256 hash is sent to
 * the provider.  This prevents authorization-code interception attacks.
 */

/**
 * Generate a cryptographically random PKCE code verifier.
 *
 * The verifier is a URL-safe base64 string of the requested length.
 * RFC 7636 recommends 43–128 characters; we default to 128.
 *
 * @param length - Number of characters in the output (default 128).
 * @returns A base64url-encoded random string.
 */
export function generateCodeVerifier(length = 128): string {
  const array = new Uint8Array(Math.ceil((length * 3) / 4));
  crypto.getRandomValues(array);
  return btoa(String.fromCharCode(...array))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "")
    .slice(0, length);
}

/**
 * Compute the PKCE code challenge from a verifier.
 *
 * The challenge is `BASE64URL(SHA-256(ASCII(verifier)))` per RFC 7636 §4.2.
 *
 * @param verifier - The code verifier produced by {@link generateCodeVerifier}.
 * @returns A promise that resolves to the base64url-encoded SHA-256 hash.
 */
export async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

// Session-storage keys used across the OAuth flow.
const VERIFIER_KEY = "oauth_code_verifier";
const PROVIDER_KEY = "oauth_provider";

/** Persist the code verifier and provider name for retrieval on the callback page. */
export function storeOAuthSession(provider: string, verifier: string): void {
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(PROVIDER_KEY, provider);
}

/** Read the stored code verifier (returns null if absent). */
export function getStoredVerifier(): string | null {
  return sessionStorage.getItem(VERIFIER_KEY);
}

/** Read the stored OAuth provider (returns null if absent). */
export function getStoredProvider(): string | null {
  return sessionStorage.getItem(PROVIDER_KEY);
}

/** Clear the stored OAuth session data. */
export function clearOAuthSession(): void {
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(PROVIDER_KEY);
}
