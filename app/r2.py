"""Cloudflare R2 (S3 API) uploads for the Etsy listing images, without extra packages.

Same settings as the binder pipeline (Replit Secrets): R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_BASE_URL (e.g. https://assets.olliepagecreations.com),
optional R2_ENDPOINT. Optional CDN purge: CLOUDFLARE_API_TOKEN + CLOUDFLARE_ZONE_ID.
Requests are signed with AWS Signature Version 4 (region "auto", path-style URLs).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class R2Config:
    account_id: str
    access_key: str
    secret_key: str
    bucket: str
    public_base: str
    endpoint: str
    cf_token: str = ""
    cf_zone: str = ""

    @staticmethod
    def from_env(env=os.environ) -> "R2Config | None":
        need = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL")
        if not all(env.get(k) for k in need):
            return None
        endpoint = env.get("R2_ENDPOINT") or f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
        return R2Config(env["R2_ACCOUNT_ID"], env["R2_ACCESS_KEY_ID"], env["R2_SECRET_ACCESS_KEY"], env["R2_BUCKET"],
                        env["R2_PUBLIC_BASE_URL"].rstrip("/"), endpoint.rstrip("/"),
                        env.get("CLOUDFLARE_API_TOKEN", ""), env.get("CLOUDFLARE_ZONE_ID", ""))

    def public_url(self, key: str) -> str:
        return f"{self.public_base}/{quote(key)}"


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sign_v4(method: str, host: str, path: str, headers: dict[str, str], payload_hash: str, access_key: str,
            secret_key: str, region: str, now: _dt.datetime, service: str = "s3", query: str = "") -> dict[str, str]:
    """Headers for an AWS SigV4-signed request (adds host, x-amz-date, x-amz-content-sha256, Authorization).
    `path` must already be URI-encoded."""
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    h = {k.lower(): v.strip() for k, v in headers.items()}
    h.update({"host": host, "x-amz-date": amz_date, "x-amz-content-sha256": payload_hash})
    names = sorted(h)
    canonical = "\n".join([method, path, query, "".join(f"{k}:{h[k]}\n" for k in names), ";".join(names),
                           payload_hash])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret_key).encode(), day), region), service), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    h["authorization"] = (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={';'.join(names)}, "
                          f"Signature={signature}")
    return h


class R2Error(RuntimeError):
    pass


def put_object(cfg: R2Config, key: str, data: bytes, content_type: str = "image/png",
               cache_control: str = "public, max-age=60, must-revalidate", timeout: float = 60) -> str:
    """Upload one object; returns its public URL."""
    host = cfg.endpoint.split("://", 1)[1]
    path = f"/{quote(cfg.bucket)}/{quote(key)}"
    headers = sign_v4("PUT", host, path, {"content-type": content_type, "cache-control": cache_control},
                      hashlib.sha256(data).hexdigest(), cfg.access_key, cfg.secret_key, "auto",
                      _dt.datetime.now(_dt.timezone.utc))
    headers.pop("host")
    req = urllib.request.Request(cfg.endpoint + path, data=data, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 300:
                raise R2Error(f"R2 upload of {key} failed ({resp.status}).")
    except urllib.error.HTTPError as e:
        raise R2Error(f"R2 refused the upload of {key} ({e.code}): check the R2_* secrets.") from e
    except urllib.error.URLError as e:
        raise R2Error(f"Could not reach R2 to upload {key}: {e.reason}") from e
    except OSError as e:                       # timeouts, dropped connections
        raise R2Error(f"The upload of {key} to R2 was interrupted ({e}).") from e
    return cfg.public_url(key)


def purge_cdn(cfg: R2Config, urls: list[str]) -> bool:
    """Best effort: ask Cloudflare to forget the old copies (30 URLs per call)."""
    if not (cfg.cf_token and cfg.cf_zone) or not urls:
        return False
    ok = True
    for i in range(0, len(urls), 30):
        req = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4/zones/{cfg.cf_zone}/purge_cache", method="POST",
            data=json.dumps({"files": urls[i:i + 30]}).encode(),
            headers={"Authorization": f"Bearer {cfg.cf_token}", "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=20).close()
        except (urllib.error.URLError, OSError):
            ok = False
    return ok
