"""
proxy_manager.py — Free rotating proxy pool for YouTube transcript fetching.

Sources → test concurrently → round-robin rotation → auto-refresh when low.
Dead proxies are never retried within a session.
"""

import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

_SOURCES = [
    "https://api.proxyscrape.com/v3/free-proxy-list/get"
    "?request=displayproxies&protocol=http&timeout=5000"
    "&country=all&ssl=all&anonymity=elite,anonymous",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
]

_TEST_TIMEOUT = 6    # seconds per proxy test
_MAX_TEST    = 300   # max raw proxies to test per build cycle

# Test against YouTube directly — filters to proxies that can actually reach it
_TEST_URL    = "https://www.youtube.com/robots.txt"
_TEST_KEYWORD = "Disallow"
_TEST_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


class ProxyManager:
    def __init__(self):
        self.working_proxies: list[str] = []
        self.dead_proxies:    set[str]  = set()
        self.current_index:   int       = 0
        self.lock                       = threading.Lock()
        self._refresh_thread: threading.Thread | None = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _next_proxy_str(self) -> str | None:
        """Round-robin next proxy. Must be called under self.lock."""
        if not self.working_proxies:
            return None
        if len(self.working_proxies) < 5:
            self._maybe_refresh_bg()
        proxy = self.working_proxies[self.current_index % len(self.working_proxies)]
        self.current_index += 1
        return proxy

    def _maybe_refresh_bg(self) -> None:
        """Start background pool refresh if none is running. Must be under self.lock."""
        if self._refresh_thread is None or not self._refresh_thread.is_alive():
            print(f"[Proxy] Pool low ({len(self.working_proxies)} remaining) — refreshing in background...")
            self._refresh_thread = threading.Thread(
                target=self.build_pool, daemon=True
            )
            self._refresh_thread.start()

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch_raw_proxies(self) -> list[str]:
        seen: set[str] = set()
        proxies: list[str] = []
        for src in _SOURCES:
            try:
                resp = requests.get(src, timeout=10)
                if resp.status_code != 200:
                    continue
                for line in resp.text.splitlines():
                    line = line.strip()
                    if (
                        line
                        and ":" in line
                        and line not in seen
                        and line not in self.dead_proxies
                    ):
                        seen.add(line)
                        proxies.append(line)
            except Exception:
                pass
        print(f"[Proxy] Fetched {len(proxies)} raw proxies from sources")
        return proxies

    def test_proxy(self, proxy: str) -> bool:
        try:
            p = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
            r = requests.get(
                _TEST_URL, proxies=p, timeout=_TEST_TIMEOUT, headers=_TEST_HEADERS
            )
            return r.status_code == 200 and _TEST_KEYWORD in r.text
        except Exception:
            return False

    def build_pool(self, min_proxies: int = 20) -> None:
        raw = self.fetch_raw_proxies()
        candidates = [p for p in raw if p not in self.dead_proxies][:_MAX_TEST]
        found: list[str] = []

        print("[Proxy] Testing proxies... (this takes ~30 seconds)")

        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = {executor.submit(self.test_proxy, p): p for p in candidates}
            for future in as_completed(futures):
                proxy = futures[future]
                try:
                    if future.result() and proxy not in self.dead_proxies:
                        found.append(proxy)
                        if len(found) >= min_proxies:
                            for f in futures:
                                f.cancel()
                            break
                except Exception:
                    pass

        with self.lock:
            existing = set(self.working_proxies)
            for p in found:
                if p not in existing:
                    self.working_proxies.append(p)
            self.current_index = 0
            total = len(self.working_proxies)

        if total < 5:
            print(
                f"[Proxy] Warning: only {total} working proxies found"
                " — free proxies may be exhausted"
            )
        else:
            print(f"[Proxy] Pool ready — {total} working proxies found")

    def get_proxy(self) -> dict | None:
        """Next proxy as requests-compatible dict {http: ..., https: ...}."""
        with self.lock:
            p = self._next_proxy_str()
        if p is None:
            return None
        return {"http": f"http://{p}", "https": f"http://{p}"}

    def get_proxy_string(self) -> str | None:
        """Next proxy as 'ip:port' string (used by yt-dlp)."""
        with self.lock:
            return self._next_proxy_str()

    def mark_dead(self, proxy_str: str) -> None:
        """Remove a proxy from the pool permanently for this session."""
        with self.lock:
            if proxy_str in self.working_proxies:
                self.working_proxies.remove(proxy_str)
            self.dead_proxies.add(proxy_str)
            print(
                f"[Proxy] Removed dead proxy — {len(self.working_proxies)} remaining in pool"
            )
