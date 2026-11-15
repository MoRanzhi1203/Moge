#!/usr/bin/env python3
"""Fetch openly licensed sample images for Moge from Wikimedia Commons.

Only CC0 / Public Domain / CC BY (without SA) files are accepted. Each file's
license metadata is read from the Commons API before download; ambiguous or
disallowed licenses are skipped. Synthetic gradients are generated locally.
"""
from __future__ import annotations

import hashlib
import html
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "assets" / "samples"
THUMBS = SAMPLES / "thumbnails"
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "MogeSampleFetcher/1.0 (https://github.com/MoRanzhi1203/Moge; local test assets)"

TARGETS = {
    "portraits": 3,
    "animals": 3,
    "landscapes": 3,
    "flowers": 2,
    "architecture": 2,
    "illustrations": 2,
    "transparent": 2,
}

SEARCH_TERMS = {
    "portraits": ["portrait photograph", "man portrait", "woman portrait", "portrait studio"],
    "animals": ["cat photograph", "dog portrait", "bird photograph", "rabbit photograph"],
    "landscapes": ["mountain landscape", "forest landscape", "beach sunset", "lake landscape"],
    "flowers": ["flower close-up", "rose photograph", "tulip photograph"],
    "architecture": ["building facade", "bridge architecture", "historic building"],
    "illustrations": ["public domain illustration", "vintage book illustration", "cartoon public domain"],
    "transparent": ["logo transparent", "symbol png", "public domain icon png", "free logo png"],
}

BAD_LICENSE_TOKENS = ("sa", "nc", "nd", "fair use", "non-free")
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_SIDE = 1400
THUMB_SIDE = 360


def api_get(params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(8 * (attempt + 1))
            elif attempt == 3:
                raise
            else:
                time.sleep(2 * (attempt + 1))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    return {}


def license_ok(name: str) -> bool:
    text = (name or "").lower()
    if not text:
        return False
    if any(token in text for token in BAD_LICENSE_TOKENS):
        return False
    return (
        "cc0" in text
        or "public domain" in text
        or text in ("pd", "pd-art", "pd-usgov")
        or ("cc by" in text)
    )


def clean(value) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    text = html.unescape(str(value or ""))
    text = text.replace("<br />", " ").replace("<br>", " ")
    while "<" in text and ">" in text:
        start = text.find("<")
        end = text.find(">", start)
        if end < 0:
            break
        text = text[:start] + " " + text[end + 1:]
    return " ".join(text.split())


def search(term: str, limit: int = 30) -> list[dict]:
    time.sleep(2)
    data = api_get(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {term}",
            "gsrnamespace": 6,
            "gsrlimit": limit,
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": MAX_SIDE,
        }
    )
    pages = (data.get("query") or {}).get("pages") or {}
    results = []
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        item = dict(infos[0])
        item["title"] = page.get("title") or item.get("title") or ""
        results.append(item)
    return results


def pick(info: dict, category: str) -> dict | None:
    meta = info.get("extmetadata") or {}
    license_name = clean(meta.get("LicenseShortName")) or clean(meta.get("UsageTerms"))
    if not license_ok(license_name):
        return None
    mime = str(info.get("mime") or "")
    if mime not in ("image/jpeg", "image/png"):
        return None
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    if min(width, height) < 320:
        return None
    author = clean(meta.get("Artist")) or clean(meta.get("Credit")) or "Unknown"
    license_url = clean(meta.get("LicenseUrl"))
    description = clean(meta.get("ImageDescription"))
    url = info.get("thumburl") if mime == "image/jpeg" else info.get("url")
    if not url:
        return None
    return {
        "title": str(info.get("title") or "").replace("File:", ""),
        "source_url": info.get("descriptionurl") or "",
        "author": author,
        "license": license_name,
        "license_url": license_url,
        "description": description,
        "mime": mime,
        "url": url,
        "width": width,
        "height": height,
        "category": category,
    }


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        length = int(response.headers.get("Content-Length") or 0)
        if length and length > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"file too large: {length} bytes")
        return response.read()


def resize_image(image: np.ndarray) -> tuple[np.ndarray, bool]:
    height, width = image.shape[:2]
    longest = max(width, height)
    if longest <= MAX_SIDE:
        return image, False
    scale = MAX_SIDE / float(longest)
    return cv2.resize(
        image, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA
    ), True


def save_image(image: np.ndarray, target: Path) -> None:
    suffix = target.suffix.lower()
    if suffix == ".png":
        data = cv2.imencode(".png", image)[1].tobytes()
    else:
        rgb = image[..., :3] if image.ndim == 3 else image
        data = cv2.imencode(".jpg", rgb, [int(cv2.IMWRITE_JPEG_QUALITY), 90])[1].tobytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def make_thumbnail(source: Path, target: Path) -> None:
    image = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
    if image is None:
        return
    height, width = image.shape[:2]
    scale = THUMB_SIDE / float(max(width, height))
    resized = cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), resized)


def make_credits(entries: list[dict]) -> str:
    lines = [
        "# 示例图片许可与署名",
        "",
        "本目录图片来自 Wikimedia Commons，仅选用 CC0 / Public Domain / CC BY（不含 SA）作品。",
        "图片许可独立于 Moge 软件许可；下载时已按各自许可记录作者与来源。",
        "",
        "| 文件 | 标题 | 作者 | 许可 | 来源 |",
        "|---|---|---|---|---|",
    ]
    for item in entries:
        lines.append(
            f"| {item['filename']} | {item['title']} | {item['author']} | "
            f"[{item['license']}]({item.get('license_url') or item['source_url']}) | "
            f"[Commons]({item['source_url']}) |"
        )
    lines.append("")
    lines.append("修改说明：图片可能被等比缩放至长边不超过 1400 像素，并生成缩略图；未做内容裁剪或重新上色。")
    return "\n".join(lines) + "\n"


def synthetic_images() -> list[dict]:
    entries = []
    category = "synthetic"
    target_dir = SAMPLES / category
    target_dir.mkdir(parents=True, exist_ok=True)

    width, height = 1024, 768
    rgb = np.zeros((height, width, 3), np.uint8)
    hue = np.linspace(0, 179, width, dtype=np.float32)[None, :]
    hsv = np.zeros((height, width, 3), np.uint8)
    hsv[..., 0] = hue.astype(np.uint8)
    hsv[..., 1] = 255
    hsv[..., 2] = np.linspace(255, 40, height, dtype=np.float32)[:, None].astype(np.uint8)
    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    cv2.putText(rgb, "Moge RGB Gradient", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
    gradient = target_dir / "gradient_rgb.png"
    save_image(rgb, gradient)

    matrix = np.zeros((720, 960, 3), np.uint8)
    colors = [
        (40, 40, 200), (40, 160, 230), (60, 200, 220), (80, 190, 80),
        (220, 210, 60), (40, 130, 240), (180, 80, 200), (200, 200, 200),
    ]
    for row in range(3):
        for col in range(6):
            color = colors[(row * 6 + col) % len(colors)]
            x0, y0 = col * 160, row * 160
            matrix[y0:y0 + 160, x0:x0 + 160] = color
    for index in range(10):
        value = int(255 * index / 9)
        matrix[480:600, index * 96:(index + 1) * 96] = (value, value, value)
    matrix[600:720, :] = np.linspace(0, 255, 960, dtype=np.float32)[None, :, None].astype(np.uint8)
    cv2.putText(matrix, "Moge Color Matrix", (24, 640), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    colour = target_dir / "color_matrix.png"
    save_image(matrix, colour)

    for index, (path, recommended) in enumerate(((gradient, (64, 48)), (colour, (64, 48)))):
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        height, width = image.shape[:2]
        thumb = THUMBS / f"{category}-{index + 1}.png"
        make_thumbnail(path, thumb)
        entries.append(
            {
                "id": f"{category}-{index + 1}",
                "title": "RGB 渐变" if index == 0 else "色块与灰阶矩阵",
                "category": category,
                "filename": str(path.relative_to(SAMPLES)).replace("\\", "/"),
                "thumbnail": str(thumb.relative_to(SAMPLES)).replace("\\", "/"),
                "source_url": "Moge synthetic test image",
                "author": "Moge Project",
                "license": "CC0-1.0 (generated)",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "attribution": "Moge Project synthetic image",
                "description": "程序生成的色阶/渐变测试图，无第三方版权。",
                "resized": False,
                "recommended_grid": {"width": recommended[0], "height": recommended[1]},
                "synthetic": True,
            }
        )
    return entries


def main() -> int:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    entries = synthetic_images()
    seen_sha = {item["sha256"] for item in entries}
    report = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "skipped": [], "accepted": []}

    for category, target_count in TARGETS.items():
        count = 0
        for term in SEARCH_TERMS[category]:
            if count >= target_count:
                break
            try:
                pages = search(term)
            except Exception as exc:
                report["skipped"].append({"category": category, "term": term, "reason": f"search: {exc}"})
                continue
            for info in pages:
                if count >= target_count:
                    break
                candidate = pick(info, category)
                if candidate is None:
                    continue
                try:
                    payload = download(candidate["url"])
                except Exception as exc:
                    report["skipped"].append(
                        {"category": category, "title": candidate["title"], "reason": f"download: {exc}"}
                    )
                    continue
                digest = hashlib.sha256(payload).hexdigest()
                if digest in seen_sha:
                    continue
                image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_UNCHANGED)
                if image is None:
                    continue
                if category == "transparent":
                    if image.ndim != 3 or image.shape[2] != 4 or int(image[..., 3].min()) >= 250:
                        report["skipped"].append(
                            {"category": category, "title": candidate["title"], "reason": "no alpha"}
                        )
                        continue
                image, resized = resize_image(image)
                suffix = ".png" if candidate["mime"] == "image/png" else ".jpg"
                entry_id = f"{category}-{count + 1}"
                filename = f"{entry_id}{suffix}"
                target = SAMPLES / category / filename
                save_image(image, target)
                file_digest = hashlib.sha256(target.read_bytes()).hexdigest()
                thumb = THUMBS / f"{entry_id}.jpg"
                make_thumbnail(target, thumb)
                width, height = image.shape[1], image.shape[0]
                ratio = width / height
                if ratio > 1.25:
                    grid = (64, max(16, round(64 / ratio)))
                elif ratio < 0.8:
                    grid = (max(16, round(64 * ratio)), 64)
                else:
                    grid = (64, 64)
                entry = {
                    "id": entry_id,
                    "title": candidate["title"],
                    "category": category,
                    "filename": str(target.relative_to(SAMPLES)).replace("\\", "/"),
                    "thumbnail": str(thumb.relative_to(SAMPLES)).replace("\\", "/"),
                    "source_url": candidate["source_url"],
                    "author": candidate["author"],
                    "license": candidate["license"],
                    "license_url": candidate["license_url"],
                    "width": width,
                    "height": height,
                    "sha256": file_digest,
                    "attribution": f"{candidate['author']} / Wikimedia Commons / {candidate['license']}",
                    "description": candidate["description"],
                    "resized": resized,
                    "recommended_grid": {"width": grid[0], "height": grid[1]},
                    "original_width": candidate["width"],
                    "original_height": candidate["height"],
                }
                entries.append(entry)
                seen_sha.add(file_digest)
                report["accepted"].append(
                    {"category": category, "title": candidate["title"], "license": candidate["license"]}
                )
                count += 1
                print(f"[{category}] {filename} <- {candidate['title']} ({candidate['license']})")

    manifest = {
        "schema": 1,
        "generated_at": report["generated_at"],
        "count": len(entries),
        "categories": sorted(TARGETS) + ["synthetic"],
        "images": entries,
    }
    (SAMPLES / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (SAMPLES / "CREDITS.md").write_text(make_credits(entries), encoding="utf-8")
    (ROOT / "docs" / "sample-images-acquisition.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"total {len(entries)} images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
