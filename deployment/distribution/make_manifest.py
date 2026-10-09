"""Generate a validated, channel-specific manifest from published Docker digest."""
import argparse
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--channel", choices=("staging", "production"), required=True)
parser.add_argument("--image", required=True)
parser.add_argument("--version", required=True)
parser.add_argument("--destination", required=True)
args = parser.parse_args()
if not re.fullmatch(r"ghcr\.io/[a-z0-9/_-]+@sha256:[a-f0-9]{64}", args.image):
    parser.error("Docker image must use an immutable GHCR digest.")
payload = {
    "schema_version": 1,
    "channel": args.channel,
    "manager_version": args.version,
    "weave_api_base_url": ("https://api.weavecloudspace.com" if args.channel == "production"
                           else "https://weave-staging-api-staging.up.railway.app"),
    "cbt_image": args.image,
    "ubuntu": {
        "version": "24.04",
        "download_url": "https://cloud-images.ubuntu.com/wsl/releases/noble/current/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz",
        "sha256": "2a790896740b14d637dbdc583cce1ba081ac53b9e9cdb46dc09a2f73abbd9934",
    },
}
target = Path(args.destination)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
