export function isExactCatoDaemonUrl(
  rawUrl: string,
  daemonOrigin: string,
  pageUrl: string,
): boolean {
  try {
    return new URL(rawUrl, pageUrl).origin === daemonOrigin;
  } catch {
    return false;
  }
}

export function installCatoFetchAuth(token: string | undefined, daemonPort: number): void {
  const w = window as Window & {
    __CATO_DAEMON_TOKEN__?: string;
    __CATO_DAEMON_ORIGIN__?: string;
    __CATO_FETCH_PATCHED__?: boolean;
    __CATO_ORIGINAL_FETCH__?: typeof window.fetch;
  };
  if (!token) {
    delete w.__CATO_DAEMON_TOKEN__;
    delete w.__CATO_DAEMON_ORIGIN__;
    return;
  }
  w.__CATO_DAEMON_TOKEN__ = token;
  w.__CATO_DAEMON_ORIGIN__ = `http://127.0.0.1:${daemonPort}`;
  if (w.__CATO_FETCH_PATCHED__) return;

  const originalFetch = window.fetch.bind(window);
  w.__CATO_ORIGINAL_FETCH__ = originalFetch;
  w.__CATO_FETCH_PATCHED__ = true;

  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const rawUrl = input instanceof Request ? input.url : String(input);
    const isCatoDaemonOrigin = Boolean(
      w.__CATO_DAEMON_ORIGIN__ &&
      isExactCatoDaemonUrl(rawUrl, w.__CATO_DAEMON_ORIGIN__, window.location.href),
    );

    if (!isCatoDaemonOrigin || !w.__CATO_DAEMON_TOKEN__) {
      return originalFetch(input, init);
    }

    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    );
    if (!headers.has("X-Cato-Token")) {
      headers.set("X-Cato-Token", w.__CATO_DAEMON_TOKEN__);
    }

    if (input instanceof Request) {
      return originalFetch(new Request(input, { ...init, headers }));
    }
    return originalFetch(input, { ...init, headers });
  };
}
