#!/usr/bin/env python3
"""
カーセンサー 複数URL統合スクレイパー
GitHub Actionsで定期実行し、docs/data.json に保存する
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os
from datetime import datetime

# スクレイピング対象URL一覧（ラベル付き）
SEARCH_URLS = [
    {
        "label": "リトルノオクタービア",
        "url": "https://www.carsensor.net/usedcar/freeword/%E3%83%AA%E3%83%88%E3%83%AB%E3%83%8E%E3%82%AA%E3%82%AF%E3%82%BF%E3%83%BC%E3%83%93%E3%82%A2/index.html"
    },
    {
        "label": "キャンパー鹿児島",
        "url": "https://www.carsensor.net/usedcar/freeword/%E3%82%AD%E3%83%A3%E3%83%B3%E3%83%91%E3%83%BC%E9%B9%BF%E5%85%90%E5%B3%B6/index2.html?SORT=2"
    },
    {
        "label": "キャンピングカー",
        "url": "https://www.carsensor.net/usedcar/freeword/%E3%82%AD%E3%83%A3%E3%83%B3%E3%83%94%E3%83%B3%E3%82%B0%E3%82%AB%E3%83%BC/index3.html?SORT=21"
    },
    {
        "label": "トイファクトリー",
        "url": "https://www.carsensor.net/usedcar/freeword/%E3%83%88%E3%82%A4%E3%83%95%E3%82%A1%E3%82%AF%E3%83%88%E3%83%AA%E3%83%BC/index2.html?SORT=2"
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
        "label": "アストンマーティン AM_S022 (2019〜)",
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


def scrape_url(search_info):
    """指定URLから車両リストをスクレイピングする"""
    label = search_info["label"]
    url = search_info["url"]
    print(f"  スクレイピング中: {label}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        # 件数取得
        count_el = soup.find(class_=re.compile(r"hitCount|hitNum|searchCount|resultCount"))
        if not count_el:
            count_el = soup.find("span", class_=re.compile(r"count|Count"))
        total_count = count_el.get_text(strip=True) if count_el else "不明"

        # 車両カード取得
        car_cards = soup.find_all("div", id=re.compile(r"_cas$"))
        print(f"  取得件数: {len(car_cards)}件")

        cars = []
        for card in car_cards:
            try:
                car = parse_car_card(card, label)
                cars.append(car)
            except Exception as e:
                print(f"  カード解析エラー: {e}")

        return {
            "label": label,
            "url": url,
            "total_count": total_count,
            "scraped_count": len(cars),
            "cars": cars,
            "error": None,
            "scraped_at": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"  エラー: {e}")
        return {
            "label": label,
            "url": url,
            "total_count": "0",
            "scraped_count": 0,
            "cars": [],
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
            time.sleep(2)
    return results


if __name__ == "__main__":
    print("カーセンサー スクレイピング開始...")
    results = scrape_all()

    # docs/data.json に保存（GitHub Pages用）
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "data.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n完了。結果を {output_path} に保存しました。")
    total_cars = sum(r["scraped_count"] for r in results)
    print(f"合計取得台数: {total_cars}台")
    for r in results:
        print(f"  [{r['label']}] {r['scraped_count']}台 (エラー: {r['error']})")
