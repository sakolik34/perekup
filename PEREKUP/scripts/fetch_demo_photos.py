"""Однократная загрузка иллюстраций из проверенных страниц Wikimedia Commons."""

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import quote

import httpx

PHOTOS = [
    (
        "golf-front",
        "Volkswagen GOLF VII TSI front.JPG",
        "Tokumeigakarinoaoshima",
        "CC0 1.0",
        "https://creativecommons.org/publicdomain/zero/1.0/",
    ),
    (
        "golf-rear",
        "Volkswagen GOLF VII TSI rear.JPG",
        "Tokumeigakarinoaoshima",
        "CC0 1.0",
        "https://creativecommons.org/publicdomain/zero/1.0/",
    ),
    (
        "octavia-front",
        "Skoda Octavia III TDI Front.JPG",
        "Thomas doerfer",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    (
        "octavia-rear",
        "Skoda Octavia III TDI Heck.JPG",
        "Thomas doerfer",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    (
        "megane-front",
        "Renault Mégane front.jpg",
        "Rutger van der Maar",
        "CC BY 2.0",
        "https://creativecommons.org/licenses/by/2.0/",
    ),
    (
        "camry-front",
        "Toyota Camry 2.5Q, XV50 front view.jpg",
        "EurovisionNim",
        "CC BY-SA 4.0",
        "https://creativecommons.org/licenses/by-sa/4.0/",
    ),
    (
        "mazda-front",
        "Mazda MX-5 (ND) in Jambi City (front view).jpg",
        "Firzafp",
        "CC BY-SA 4.0",
        "https://creativecommons.org/licenses/by-sa/4.0/",
    ),
]


def main():
    root = Path(__file__).resolve().parents[1] / "app" / "static" / "cars"
    root.mkdir(exist_ok=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=[p[0] for p in PHOTOS])
    args = parser.parse_args()
    manifest = (
        json.loads((root / "credits.json").read_text()) if (root / "credits.json").exists() else []
    )
    with httpx.Client(
        timeout=40,
        follow_redirects=True,
        headers={"User-Agent": "PerekupDemo/0.2 (local educational project)"},
    ) as client:
        for name, title, author, license_name, license_url in PHOTOS:
            if args.only and name != args.only:
                continue
            page_url = "https://commons.wikimedia.org/wiki/File:" + quote(title.replace(" ", "_"))
            page = client.get(page_url)
            page.raise_for_status()
            content = page.text
            Path("/tmp/perekup-" + name + ".html").write_text(content)
            match = re.search(r'<div class="fullImageLink".*?<img[^>]+src="([^"]+)"', content, re.S)
            if not match:
                raise RuntimeError("Не найдено изображение: " + title)
            image_url = html.unescape(match.group(1))
            if image_url.startswith("//"):
                image_url = "https:" + image_url
            if not image_url.startswith(
                ("https://upload.wikimedia.org/", "https://thumb.wikimedia.org/")
            ):
                raise RuntimeError("Неожиданный адрес изображения")
            response = client.get(image_url)
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("image/"):
                raise RuntimeError("Вместо фото получен другой формат")
            (root / (name + ".jpg")).write_bytes(response.content)
            manifest = [
                entry for entry in manifest if entry["file"] != "/static/cars/" + name + ".jpg"
            ]
            manifest.append(
                {
                    "file": "/static/cars/" + name + ".jpg",
                    "title": title,
                    "author": author,
                    "source": page_url,
                    "license": license_name,
                    "license_url": license_url,
                    "changes": "Миниатюра Wikimedia; в интерфейсе кадрируется средствами CSS.",
                }
            )
            (root / "credits.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            print(name, len(response.content), flush=True)


if __name__ == "__main__":
    main()
