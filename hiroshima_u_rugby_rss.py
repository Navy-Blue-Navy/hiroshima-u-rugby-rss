import os
import re
import time
import hashlib
import requests
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urljoin, urlparse, unquote


SOURCE_URL = "https://hiroshimaurfc.wixsite.com/hiroshima-u-rfc/blog-1"
OUTPUT_FILE = "hiroshima_u_rugby.xml"

FEED_TITLE = "広島大学ラグビー部 Blog"
FEED_LINK = SOURCE_URL
FEED_DESCRIPTION = "広島大学ラグビー部公式サイト Blog 更新情報"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

DATE_RE = re.compile(
    r"(20\d{2})年(\d{1,2})月(\d{1,2})日"
)


def fetch(url):
    last_error = None

    for attempt in range(1, 4):
        try:
            print(f"取得試行 {attempt}/3: {url}")

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print(
                f"HTTP: {response.status_code} / "
                f"取得バイト数: {len(response.content)}"
            )

            response.raise_for_status()
            response.encoding = response.apparent_encoding

            return response.text

        except Exception as e:
            last_error = e
            print(f"取得失敗: {e}")

            if attempt < 3:
                print("10秒待って再試行します。")
                time.sleep(10)

    raise RuntimeError(
        f"ページを取得できませんでした: {url} / {last_error}"
    )


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


def make_guid(link):
    return hashlib.sha256(
        link.encode("utf-8")
    ).hexdigest()


def normalize_link(href):
    link = urljoin(
        SOURCE_URL,
        href
    )

    parsed = urlparse(link)

    return (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{parsed.path}"
    )


def title_from_url(link):
    parsed = urlparse(link)

    path = unquote(
        parsed.path
    )

    if "/post/" not in path:
        return ""

    title = path.split(
        "/post/",
        1
    )[1]

    title = title.replace(
        "-",
        " "
    )

    return clean_text(title)


def find_date_near_anchor(anchor):
    current = anchor

    for _ in range(8):
        if current is None:
            break

        text = clean_text(
            current.get_text(
                " ",
                strip=True
            )
        )

        match = DATE_RE.search(
            text
        )

        if match:
            try:
                return datetime(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    12,
                    0,
                    0,
                    tzinfo=JST
                )
            except ValueError:
                pass

        current = current.parent

    return None


def extract_articles(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    articles = []
    seen_links = set()

    for a in soup.find_all(
        "a",
        href=True
    ):
        link = normalize_link(
            a["href"]
        )

        if (
            "hiroshimaurfc.wixsite.com/"
            "hiroshima-u-rfc/post/"
            not in link
        ):
            continue

        if link in seen_links:
            continue

        title = clean_text(
            a.get_text(
                " ",
                strip=True
            )
        )

        if not title:
            title = title_from_url(
                link
            )

        if not title:
            continue

        published = find_date_near_anchor(
            a
        )

        if published is None:
            print(
                "日付を取得できない記事を除外:",
                title
            )
            continue

        articles.append({
            "title": title,
            "link": link,
            "guid": make_guid(link),
            "published": published,
            "description": title,
        })

        seen_links.add(
            link
        )

    articles.sort(
        key=lambda x: x["published"],
        reverse=True
    )

    return articles


def load_existing():
    existing = {}

    if not os.path.exists(
        OUTPUT_FILE
    ):
        return existing

    tree = ET.parse(
        OUTPUT_FILE
    )

    root = tree.getroot()

    for item in root.findall(
        "./channel/item"
    ):
        title = item.findtext(
            "title",
            ""
        ).strip()

        link = item.findtext(
            "link",
            ""
        ).strip()

        guid = item.findtext(
            "guid",
            ""
        ).strip()

        pub_date = item.findtext(
            "pubDate",
            ""
        ).strip()

        description = item.findtext(
            "description",
            ""
        ).strip()

        if not link:
            continue

        try:
            published = parsedate_to_datetime(
                pub_date
            )

            if published.tzinfo is None:
                published = published.replace(
                    tzinfo=JST
                )

        except Exception:
            continue

        existing[link] = {
            "title": title,
            "link": link,
            "guid": (
                guid
                or make_guid(link)
            ),
            "published": published,
            "description": description,
        }

    return existing


def build_rss(articles):
    rss = ET.Element(
        "rss",
        version="2.0"
    )

    channel = ET.SubElement(
        rss,
        "channel"
    )

    ET.SubElement(
        channel,
        "title"
    ).text = FEED_TITLE

    ET.SubElement(
        channel,
        "link"
    ).text = FEED_LINK

    ET.SubElement(
        channel,
        "description"
    ).text = FEED_DESCRIPTION

    ET.SubElement(
        channel,
        "language"
    ).text = "ja"

    ET.SubElement(
        channel,
        "lastBuildDate"
    ).text = format_datetime(
        datetime.now(JST)
    )

    for article in articles:
        item = ET.SubElement(
            channel,
            "item"
        )

        ET.SubElement(
            item,
            "title"
        ).text = article["title"]

        ET.SubElement(
            item,
            "link"
        ).text = article["link"]

        guid = ET.SubElement(
            item,
            "guid"
        )

        guid.set(
            "isPermaLink",
            "false"
        )

        guid.text = article["guid"]

        ET.SubElement(
            item,
            "pubDate"
        ).text = format_datetime(
            article["published"]
        )

        ET.SubElement(
            item,
            "description"
        ).text = article["description"]

    tree = ET.ElementTree(
        rss
    )

    try:
        ET.indent(
            tree,
            space="  "
        )
    except AttributeError:
        pass

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True
    )


def main():
    existing = load_existing()

    print(
        f"既存RSS件数: {len(existing)}"
    )

    try:
        html = fetch(
            SOURCE_URL
        )

        current = extract_articles(
            html
        )

        print()
        print(
            f"現在の一覧から取得: "
            f"{len(current)}件"
        )

        if not current:
            raise RuntimeError(
                "記事を1件も抽出できませんでした。"
            )

        current_by_link = {
            article["link"]: article
            for article in current
        }

        new_count = sum(
            1
            for link in current_by_link
            if link not in existing
        )

        merged = dict(
            existing
        )

        merged.update(
            current_by_link
        )

        all_articles = list(
            merged.values()
        )

        all_articles.sort(
            key=lambda x: x["published"],
            reverse=True
        )

        print(
            f"新規記事: {new_count}件"
        )

        print(
            f"累積RSS件数: {len(all_articles)}"
        )

        print()
        print("最新30件:")

        for article in all_articles[:30]:
            print(
                article["published"]
                .astimezone(JST)
                .strftime("%Y-%m-%d"),
                article["title"]
            )

        build_rss(
            all_articles
        )

        print()
        print(
            f"保存完了: {OUTPUT_FILE} "
            f"({len(all_articles)}件)"
        )

    except Exception:
        print()
        print(
            "取得・解析に失敗したため、"
            "既存RSSは変更しません。"
        )
        raise


if __name__ == "__main__":
    main()