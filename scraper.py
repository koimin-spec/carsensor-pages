#!/usr/bin/env python3
"""
カーセンサー 複数URL統合スクレイパー（全ページ取得対応版）
GitHub Actionsで定期実行し、docs/data.json に保存する

ページネーション仕様:
  - カーセンサーは全URLが最終的に /usedcar/bXX/sXXX/sort/indexN.html 形式に変換される
  - 2ページ目: index2.html, 3ページ目: index3.html ...
  - ページネーションリンクのhrefを直接取得して次ページURLを決定する
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs, urljoin
from datetime import datetime

# スクレイピング対象URL一覧（ラベル付き）
SEARCH_URLS = [
    {
        "label": "リトルノオクタービア",
        "url": "https://www.carsensor.net/usedcar/freeword/%E3%83%AA%E3%83%88%E3%83%AB%E3%83%8E%E3%82%AA%E3%82%AF%E3%82%BF%E3%83%BC%E3%83%93%E3%82%A2/index.html"
    },
    {
        "label": "キャンパー鹿児島",
        "url": "https://www.carsensor.net/usedcar/freeword/%E3%82%AD%E3%83%A3%E3%83%B3%E3%83%91%E3%83%BC%E9%B9%BF%E5%85%90%E5%B3%B6/index.html?SORT=2"
    },
    {
        "label": "キャンピングカー",
        "url": "https://www.carsensor.net/usedcar/freeword/%E3%82%AD%E3%83%A3%E3%83%B3%E3%83%94%E3%83%B3%E3%82%B0%E3%82%AB%E3%83%BC/index.html?SORT=21",
        "max_cars": 100
    },
    {
        "label": "トイファクトリー",
        "url": "https://www.carsensor.net/usedcar/freeword/%E3%83%88%E3%82%A4%E3%83%95%E3%82%A1%E3%82%AF%E3%83%88%E3%83%AA%E3%83%BC/index.html?SORT=2"
    },
    {
        "label": "メルセデス S026",
        "url": "https://www.carsensor.net/usedcar/search.php?STID=CS210610&LP=ME_S026&SORT=2&CARC=ME_S026&YMIN=2015"
    },
    {
        "label": "ベンツ S560",
        "url": "https://www.carsensor.net/usedcar/search.php?STID=CS210610&SORT=2&KW=%E3%83%99%E3%83%B3%E3%83%84%20S560"
    },
    {
        "label": "メルセデス S019 (2021〜)",
        "url": "https://www.carsensor.net/usedcar/search.php?STID=CS210610&SORT=22&CARC=ME_S019&YMIN=2021"
    },
    {
        "label": "メルセデス S019 ロング (2021〜)",
        "url": "https://www.carsensor.net/usedcar/search.php?STID=CS210610&SORT=22&CARC=ME_S019&YMIN=2021&KW=%E3%83%AD%E3%83%B3%E3%82%B0"
    },
    {
        "label": "メルセデス S029 (2015〜)",
        "url": "https://www.carsensor.net/usedcar/search.php?STID=CS210610&SORT=22&CARC=ME_S029&YMIN=2015"
    },
    {
        "label": "メルセデスAMG Gクラス (2019〜)",
        "url": "https://www.carsensor.net/usedcar/search.php?STID=CS210610&LP=AM_S022&SORT=2&CARC=AM_S022&YMIN=2019"
    },
    {
        "label": "メルセデス ME_S029 (2020〜)",
        "url": "https://www.carsensor.net/usedcar/bME/s029/index.html?YMIN=2020&LP=ME_S029&SORT=2"
    }
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.carsensor.net/"
}

# 1URLあたりの最大取得ページ数（安全のため上限を設ける）
MAX_PAGES = 30


def get_total_count(soup):
    """ページから総件数を取得する"""
    # ボタンの「XX台 検索する」から取得（最も信頼性が高い）
    search_btn = soup.find("button", id="sbmt")
    if search_btn:
        text = search_btn.get_text(strip=True)
        m = re.search(r'(\d[\d,]*)', text)
        if m:
            return int(m.group(1).replace(",", ""))

    # 「XX台」テキストを広く探す
    for el in soup.find_all(string=re.compile(r'\d+台')):
        m = re.search(r'(\d[\d,]*)台', el)
        if m:
            count = int(m.group(1).replace(",", ""))
            if 1 <= count <= 99999:
                return count

    return None


def get_next_page_url_from_html(soup, current_url):
    """
    ページのHTMLから次ページのURLを取得する。
    カーセンサーのページネーションリンク（index2.html, index3.html...）を直接取得する。
    """
    # 現在のページ番号を取得
    current_page_num = 1
    m = re.search(r'index(\d+)\.html', current_url)
    if m:
        current_page_num = int(m.group(1))

    next_page_num = current_page_num + 1

    # ページネーションエリアのリンクを探す
    # 「次へ」ボタン付近のリンク、またはページ番号リンクを探す
    all_links = soup.find_all("a", href=True)
    for link in all_links:
        href = link.get("href", "")
        text = link.get_text(strip=True)

        # 次のページ番号のリンクを探す
        if text == str(next_page_num):
            full_url = urljoin("https://www.carsensor.net", href)
            return full_url

        # 「次へ」リンクを探す
        if text in ["次へ", "次"]:
            full_url = urljoin("https://www.carsensor.net", href)
            return full_url

        # index(N+1).html パターンのリンクを探す
        if f"index{next_page_num}.html" in href:
            full_url = urljoin("https://www.carsensor.net", href)
            return full_url

    return None


def has_more_pages(soup, current_url):
    """次のページが存在するかチェックする"""
    next_url = get_next_page_url_from_html(soup, current_url)
    return next_url is not None


def parse_car_card(card_div, search_label):
    """車両カード要素から情報を抽出する"""
    car = {}
    car["search_label"] = search_label

    # 車両ID
    car_id = card_div.get("id", "")
    car["car_id"] = car_id.replace("_cas", "") if car_id else ""

    # 詳細URL
    detail_link = card_div.find("a", href=re.compile(r"/usedcar/detail/"))
    if detail_link:
        href = detail_link.get("href", "")
        car["detail_url"] = ("https://www.carsensor.net" + href) if href.startswith("/") else href
    else:
        car["detail_url"] = ""

    # 車名
    title_el = card_div.find(class_="cassetteMain__title")
    if not title_el:
        title_el = card_div.find("h2") or card_div.find("h3")
    car["title"] = title_el.get_text(strip=True) if title_el else ""

    # 画像URL
    img_el = card_div.find("img")
    if img_el:
        src = img_el.get("src", "")
        if "animation" not in src and src:
            car["image_url"] = src if src.startswith("http") else "https:" + src
        else:
            data_orig = img_el.get("data-original", "")
            car["image_url"] = ("https:" + data_orig) if data_orig and not data_orig.startswith("http") else data_orig
    else:
        car["image_url"] = ""

    # 支払総額
    total_price_num = card_div.find(class_="totalPrice__mainPriceNum")
    total_price_unit = card_div.find(class_="totalPrice__unit")
    if total_price_num:
        car["total_price"] = total_price_num.get_text(strip=True) + (total_price_unit.get_text(strip=True) if total_price_unit else "万円")
    else:
        car["total_price"] = "---"

    # 車両本体価格
    base_price_num = card_div.find(class_="basePrice__mainPriceNum")
    if not base_price_num:
        base_price_num = card_div.find(class_=re.compile(r"basePrice.*Num"))
    car["base_price"] = (base_price_num.get_text(strip=True) + "万円") if base_price_num else "---"

    # スペック情報
    spec_boxes = card_div.find_all(class_="specList__detailBox")
    specs = {}
    for box in spec_boxes:
        title_el2 = box.find(class_=re.compile(r"specList__title"))
        data_el = box.find(class_=re.compile(r"specList__data"))
        if title_el2 and data_el:
            specs[title_el2.get_text(strip=True)] = data_el.get_text(strip=True)

    car["year"] = specs.get("年式", "---")
    car["mileage"] = specs.get("走行距離", "---")
    car["repair_history"] = specs.get("修復歴", "---")
    car["inspection"] = specs.get("車検", "---")
    car["warranty"] = specs.get("保証", "---")
    car["displacement"] = specs.get("排気量", "---")
    car["mission"] = specs.get("ミッション", "---")

    # 店舗名
    shop_el = card_div.find(class_="cassetteSub__shop")
    if not shop_el:
        shop_el = card_div.find(class_=re.compile(r"shop|Shop"))
    car["shop_name"] = shop_el.get_text(strip=True) if shop_el else "---"

    # 地域
    area_el = card_div.find(class_=re.compile(r"area|Area|prefecture|Prefecture"))
    car["area"] = area_el.get_text(strip=True) if area_el else "---"

    # 色
    color_el = card_div.find(class_=re.compile(r"color|Color"))
    car["color"] = color_el.get_text(strip=True) if color_el else "---"

    return car


def fetch_page(url):
    """指定URLのページを取得してBeautifulSoupオブジェクトとfinal_urlを返す"""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return BeautifulSoup(resp.text, "html.parser"), resp.url


def scrape_url(search_info):
    """指定URLから全ページの車両リストをスクレイピングする"""
    label = search_info["label"]
    base_url = search_info["url"]
    max_cars = search_info.get("max_cars", None)  # 取得上限台数（Noneは無制限）
    print(f"\n  スクレイピング中: {label}")
    print(f"  URL: {base_url}")
    if max_cars:
        print(f"  取得上限: {max_cars}台")

    all_cars = []
    seen_ids = set()
    total_count = None
    current_url = base_url
    current_page = 1

    try:
        while current_page <= MAX_PAGES:
            print(f"  ページ {current_page} を取得中: {current_url}")
            try:
                soup, final_url = fetch_page(current_url)
                # リダイレクト後のURLを使用
                if final_url != current_url:
                    print(f"  リダイレクト先: {final_url}")
                    current_url = final_url
            except Exception as e:
                print(f"  ページ取得エラー (page {current_page}): {e}")
                break

            # 1ページ目のみ総件数を取得
            if current_page == 1:
                total_count = get_total_count(soup)
                print(f"  総件数: {total_count}台")

            # 車両カード取得
            car_cards = soup.find_all("div", id=re.compile(r"_cas$"))
            print(f"  このページの車両数: {len(car_cards)}件")

            if len(car_cards) == 0:
                print(f"  車両が見つからないため終了")
                break

            # 重複チェックしながら追加
            new_count = 0
            for card in car_cards:
                try:
                    car = parse_car_card(card, label)
                    car_id = car.get("car_id", "")
                    if car_id and car_id in seen_ids:
                        continue
                    if car_id:
                        seen_ids.add(car_id)
                    all_cars.append(car)
                    new_count += 1
                except Exception as e:
                    print(f"  カード解析エラー: {e}")

            print(f"  新規追加: {new_count}件 (累計: {len(all_cars)}件)")

            # 上限台数チェック
            if max_cars and len(all_cars) >= max_cars:
                # 超過分を削除して上限に合わせる
                all_cars = all_cars[:max_cars]
                print(f"  上限台数 {max_cars}台 に達したため終了")
                break

            # 総件数から全ページ取得済みか判定
            if total_count and len(all_cars) >= total_count:
                print(f"  全件取得完了 ({len(all_cars)}/{total_count})")
                break

            # 次のページURLをHTMLから取得
            next_url = get_next_page_url_from_html(soup, current_url)
            if not next_url:
                print(f"  次のページなし → 終了")
                break

            if next_url == current_url:
                print(f"  URLが変化しないため終了")
                break

            current_url = next_url
            current_page += 1
            time.sleep(2)  # サーバー負荷軽減のため待機

        print(f"  完了: {len(all_cars)}台取得 (総件数: {total_count}台)")

        return {
            "label": label,
            "url": base_url,
            "total_count": str(total_count) if total_count else "不明",
            "scraped_count": len(all_cars),
            "cars": all_cars,
            "error": None,
            "scraped_at": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"  エラー: {e}")
        import traceback
        traceback.print_exc()
        return {
            "label": label,
            "url": base_url,
            "total_count": "0",
            "scraped_count": len(all_cars),
            "cars": all_cars,
            "error": str(e),
            "scraped_at": datetime.now().isoformat()
        }


def scrape_all():
    """全URLをスクレイピングして結果を返す"""
    results = []
    for i, search_info in enumerate(SEARCH_URLS):
        result = scrape_url(search_info)
        results.append(result)
        if i < len(SEARCH_URLS) - 1:
            time.sleep(3)
    return results


if __name__ == "__main__":
    print("カーセンサー スクレイピング開始（全ページ取得版）...")
    results = scrape_all()

    # docs/data.json に保存（GitHub Pages用）
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "data.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n完了。結果を {output_path} に保存しました。")
    total_cars = sum(r["scraped_count"] for r in results)
    print(f"\n合計取得台数: {total_cars}台")
    print(f"\n{'ラベル':<35} {'取得数':>6} {'総件数':>6} {'差異':>6}")
    print("-" * 60)
    for r in results:
        scraped = r["scraped_count"]
        total = r["total_count"]
        try:
            diff = scraped - int(total)
            diff_str = f"{diff:+d}"
        except:
            diff_str = "---"
        print(f"  {r['label']:<33} {scraped:>6}台 {total:>6}台 {diff_str:>6}")
        if r["error"]:
            print(f"    エラー: {r['error']}")
