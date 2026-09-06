"""Read-only HTTP proof against a loopback business stack and its synthetic fixture."""

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit


def read_json(path):
    content = Path(path).read_bytes()
    text = content.decode(
        "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    )
    return json.loads(text.strip().splitlines()[-1])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None


def request(base, path, host):
    redirects = []
    for _ in range(4):
        req = urllib.request.Request(base + path, headers={"Host": host})
        try:
            response = urllib.request.build_opener(NoRedirect).open(req, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            if response.status in (301, 302, 307, 308):
                destination = urlsplit(response.headers["Location"])
                if destination.netloc and destination.hostname not in {
                    host,
                    urlsplit(base).hostname,
                }:
                    raise AssertionError("Redirect escaped the synthetic fixture")
                redirects.append(
                    {
                        "status": response.status,
                        "location": response.headers["Location"],
                    }
                )
                path = destination.path + (
                    "?" + destination.query if destination.query else ""
                )
                continue
            content = response.read(2_000_001)
            assert len(content) <= 2_000_000
            return {
                "status": response.status,
                "content_type": response.headers.get("Content-Type"),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "redirects": redirects,
            }, content
    raise AssertionError("Too many redirects")


parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8896")
parser.add_argument("--fixture", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--source-hashes")
parser.add_argument("--repository", default=".")
parser.add_argument("--source-commit")
args = parser.parse_args()
assert urlsplit(args.url).hostname in {"127.0.0.1", "localhost"}
assert urlsplit(args.url).scheme == "http"
fixture = read_json(args.fixture)
assert fixture["host"].startswith("seo-public-smoke-") and fixture["host"].endswith(
    ".example.test"
)
proof = {
    "observed_at": datetime.now(UTC).isoformat(),
    "transport": args.url,
    "fixture": fixture,
    "probes": {},
    "source_commit": args.source_commit,
}

for name, path, host in (
    ("page", fixture["path"], fixture["host"]),
    ("sitemap", "/sitemap.xml", fixture["host"]),
    ("image", fixture["image_path"], fixture["host"]),
    ("image_api", fixture["image_api_path"], fixture["host"]),
    ("unknown_host_image", fixture["image_path"], "unknown-fixture.example.test"),
    ("backend_ready", "/api/v1/health/", "localhost"),
    ("frontend_health", "/healthz", "localhost"),
):
    metadata, content = request(args.url, path, host)
    proof["probes"][name] = metadata
    assert metadata["status"] == (404 if name == "unknown_host_image" else 200), (
        name,
        metadata,
    )
    if name == "page":
        assert fixture["heading"].encode() in content
        assert fixture["image_path"].encode() in content
    elif name == "sitemap":
        assert (
            fixture["host"].encode() in content and fixture["path"].encode() in content
        )
    elif name in {"image", "image_api"}:
        assert metadata["content_type"].startswith("image/png")
        assert metadata["sha256"] == fixture["image_sha256"]
    elif name in {"backend_ready", "frontend_health"}:
        proof["probes"][name]["body"] = json.loads(content)
        assert proof["probes"][name]["body"]["deployment"] == "business"
        if name == "backend_ready":
            assert proof["probes"][name]["body"]["checks"] == {
                "database": "ok",
                "cache": "ok",
            }

if args.source_hashes:
    remote = read_json(args.source_hashes)
    source = Path(args.repository) / "apps/backend/src"
    local = {
        str(path.relative_to(source)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in source.rglob("*.py")
    }
    assert remote == local, {
        "missing": sorted(set(local) - set(remote)),
        "extra": sorted(set(remote) - set(local)),
        "different": [
            key for key in local if key in remote and local[key] != remote[key]
        ],
    }
    proof["backend_source_comparison"] = {"files": len(local), "different": 0}

Path(args.output).write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
print(
    json.dumps(
        {
            "probes": {
                name: value["status"] for name, value in proof["probes"].items()
            },
            "backend_source_comparison": proof.get("backend_source_comparison"),
        }
    )
)
