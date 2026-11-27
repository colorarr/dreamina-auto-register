"""Dreamina subscription-offer detection over the native commerce protocol."""

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from curl_cffi.requests import AsyncSession

from app.models import Account

logger = logging.getLogger(__name__)

PRICE_URI = "/commerce/v1/subscription/cc_price_list"
ASIA_COMMERCE_URL = "https://commerce-api-sg.capcut.com"
US_COMMERCE_URL = "https://commerce.us.capcut.com"


def _cookies(account: Account) -> Dict[str, str]:
    raw = json.loads(account.full_cookie or "[]")
    values = raw.get("cookies", []) if isinstance(raw, dict) else raw
    return {
        item["name"]: item["value"]
        for item in values
        if isinstance(item, dict) and item.get("name") and item.get("value") is not None
    }


def _iter_products(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from _iter_products(item)
    elif isinstance(value, dict):
        if "product_id" in value and ("total_amount" in value or "intro_info" in value):
            yield value
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                yield from _iter_products(nested)


def _pick_offer(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    candidates = []
    for product in _iter_products(payload.get("all_price_list", payload)):
        total = int(product.get("total_amount") or 0)
        origin = int(product.get("origin_price_amount") or product.get("normal_amount") or 0)
        intro = product.get("intro_info") or {}
        intro_price = int(intro.get("intro_price_amount") or total or 0)
        normal_price = int(intro.get("normal_price_amount") or origin or 0)
        effective = intro_price if intro_price > 0 else total
        baseline = normal_price if normal_price > 0 else origin
        product_id = str(product.get("product_id") or "")
        discounted = baseline > 0 and effective >= 0 and effective < baseline
        promoted = any(word in product_id.lower() for word in ("activity", "discount", "intro", "trial"))
        if discounted or promoted:
            candidates.append((effective / baseline if baseline else 1, product, effective, baseline))
    if not candidates:
        return None
    _, product, effective, baseline = min(candidates, key=lambda row: row[0])
    return {
        "product_id": product.get("product_id"),
        "price_amount": effective,
        "origin_price_amount": baseline,
        "currency_code": product.get("currency_code"),
        "discount_percent": round((1 - effective / baseline) * 100) if baseline else 0,
    }


async def check_account_offer(account: Account, proxy_url: Optional[str] = None) -> Dict[str, Any]:
    """Query the account-bound price list and persist a normalized offer result."""
    account.offer_status = "checking"
    account.offer_error = None
    try:
        cookies = _cookies(account)
        if not cookies.get("sessionid") and not cookies.get("sessionid_ss"):
            raise ValueError("账号缺少有效登录 Cookie")

        region = (account.region or "jp").lower()
        try:
            saved_fingerprint = json.loads(account.fingerprint_json or "{}")
        except (TypeError, ValueError):
            saved_fingerprint = {}
        impersonate = saved_fingerprint.get("impersonate") or "chrome152_macos"
        saved_user_agent = saved_fingerprint.get("user_agent")
        base_url = US_COMMERCE_URL if region == "us" else ASIA_COMMERCE_URL
        aid = 513641
        device_time = int(time.time())
        # Sign 中的 appvr 必须与当前 Dreamina Web 版本一致。
        # 旧的 5.9.0 签名虽返回 ret=0，但服务端只下发兜底价格表，
        # 会把真实的账号优惠误判为“暂无优惠”。
        app_version = "8.4.0"
        sign = hashlib.md5(
            f"9e2c|{PRICE_URI[-7:]}|7|{app_version}|{device_time}||11ac".encode()
        ).hexdigest()
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": "https://dreamina.capcut.com",
            "referer": "https://dreamina.capcut.com/",
            "appid": str(aid),
            "appvr": app_version,
            "pf": "7",
            "device-time": str(device_time),
            "did": cookies.get("_tea_web_id", ""),
            "lan": "ja" if region == "jp" else "en",
            "loc": region,
            "sign": sign,
            "sign-ver": "1",
            "store-country-code": region,
            "store-country-code-src": "uid",
            "tdid": "",
            "uifid": cookies.get("uifid", ""),
            "user-agent": saved_user_agent or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        }
        response = None
        async with AsyncSession(proxy=proxy_url, impersonate=impersonate, timeout=30) as session:
            for attempt in range(3):
                try:
                    response = await session.post(
                        base_url + PRICE_URI,
                        json={"aid": aid, "scene": "vip", "region": "default"},
                        headers=headers,
                        cookies=cookies,
                    )
                    break
                except Exception:
                    if attempt == 2:
                        raise
        if response is None:
            raise RuntimeError("价格表接口未返回响应")
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:180]}")
        outer = response.json()
        if str(outer.get("ret")) != "0":
            raise RuntimeError(outer.get("errmsg") or f"ret={outer.get('ret')}")
        payload = outer.get("data") or outer.get("response") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        offer = _pick_offer(payload)
        account.offer_checked_at = datetime.utcnow()
        account.offer_status = "eligible" if offer else "ineligible"
        account.offer_product_id = offer.get("product_id") if offer else None
        account.offer_price_amount = offer.get("price_amount") if offer else None
        account.offer_origin_price_amount = offer.get("origin_price_amount") if offer else None
        account.offer_currency_code = offer.get("currency_code") if offer else None
        account.offer_discount_percent = offer.get("discount_percent") if offer else None
        account.offer_error = None
        return {"status": account.offer_status, "offer": offer}
    except Exception as exc:
        account.offer_status = "error"
        account.offer_checked_at = datetime.utcnow()
        account.offer_error = str(exc)[:512]
        logger.warning("Offer check failed for %s: %s", account.email, exc)
        return {"status": "error", "offer": None, "error": account.offer_error}
