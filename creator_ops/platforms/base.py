from __future__ import annotations

import hashlib
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Protocol

from playwright.async_api import Page, async_playwright

from creator_ops.domain import AccountProfile, MetricRecord
from tools.browser_launcher import BrowserLauncher


class CreatorCollector(Protocol):
    async def collect(self, profile: AccountProfile, **kwargs: Any) -> list[MetricRecord]: ...


def parse_metric_number(value: Any) -> int | float | str:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "N/A", "n/a"}:
        return 0
    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10_000.0
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000.0
        text = text[:-1]
    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1]
    try:
        number = float(text) * multiplier
    except ValueError:
        return str(value).strip()
    if is_percent or not number.is_integer():
        return number
    return int(number)


def parse_published_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    for pattern in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y年%m月%d日 %H:%M",
        "%Y年%m月%d日",
    ):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def make_content_key(
    *,
    platform: str,
    profile_key: str,
    title: str,
    published_at: datetime | None,
    explicit_id: str = "",
) -> str:
    if explicit_id.strip():
        return explicit_id.strip()
    source = "|".join(
        (platform, profile_key, title.strip(), published_at.isoformat() if published_at else "")
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]


@asynccontextmanager
async def persistent_page(
    profile_path: Path,
    *,
    headless: bool = False,
) -> AsyncIterator[Page]:
    launcher = BrowserLauncher()
    browser_paths = launcher.detect_browser_paths()
    if not browser_paths:
        raise RuntimeError("Chrome or Edge was not found")
    debug_port = launcher.find_available_port()
    launcher.launch_browser(
        browser_path=browser_paths[0],
        debug_port=debug_port,
        headless=headless,
        user_data_dir=str(profile_path),
    )
    if not launcher.wait_for_browser_ready(debug_port, timeout=60):
        launcher.cleanup()
        raise RuntimeError("browser did not expose its CDP endpoint within 60 seconds")

    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{debug_port}"
            )
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            yield page
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        launcher.cleanup()


async def save_diagnostic(page: Page, platform: str, reason: str) -> Path:
    directory = Path("runtime") / "creator_ops" / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "-", reason).strip("-")[:40]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = directory / f"{platform}-{safe_reason or 'failure'}-{timestamp}.png"
    await page.screenshot(path=str(target), full_page=True)
    return target


async def locator_text(locator: Any) -> str:
    if await locator.count() == 0:
        return ""
    return (await locator.first.inner_text()).strip()
