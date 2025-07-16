import os
import requests
import json
from bs4 import BeautifulSoup
from notion_client import Client

# --- 設定項目 (GitHub Secretsから読み込む) ---
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("DATABASE_ID")

# Notionクライアントの初期化
notion = Client(auth=NOTION_API_KEY)

def scrape_cmoa_data(url):
    """コミックシーモアのページからデータを取得する"""
    try:
        exclusion_phrases = [
            'コミックシーモアなら期間限定1巻無料！',
            'コミックシーモアなら期間限定1巻立読み増量中！',
            'コミックシーモアなら期間限定1巻値引き！'
        ]
        genre_rename_map = {
            '少年マンガ': '少年',
            '青年マンガ': '青年',
            '少女マンガ': '少女',
            '女性マンガ': '女性'
        }

        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. あらすじ取得
        synopsis = ""
        # 方法A: ld+jsonから取得を試みる
        script_tag = soup.find("script", type="application/ld+json")
        if script_tag:
            try:
                clean_string = script_tag.string.encode('utf-8').decode('utf-8')
                json_data = json.loads(clean_string)
                synopsis = json_data.get("description", "")
            except Exception:
                synopsis = "" # パース失敗時は空にする

        # === 変更点: あらすじ取得の代替案を追加 ===
        # 方法B: 方法Aで取得できなかった場合、別の場所から取得する
        if not synopsis:
            description_div = soup.select_one("div#comic_description p")
            if description_div:
                # div内の<br>タグを改行文字に変換する
                for br in description_div.find_all("br"):
                    br.replace_with("\n")
                synopsis = description_div.get_text()

        # 取得したあらすじの整形処理
        synopsis = synopsis.replace("<br>", "\n")
        for phrase in exclusion_phrases:
            synopsis = synopsis.replace(phrase, "")
        synopsis = synopsis.strip()
        # =======================================

        # 2. ジャンル取得
        genres = []
        genre_tags = soup.select('.category_line_f_r_l a[href*="/genre/"]')
        for tag in genre_tags:
            genre_text = tag.get_text(strip=True)
            cleaned_genre = genre_text.split('(')[0].strip()
            renamed_genre = genre_rename_map.get(cleaned_genre, cleaned_genre)
            genres.append(renamed_genre)
        
        # 3. 雑誌・レーベル取得
        magazine = ""
        magazine_tag = soup.select_one('span.brCramb_m > a[href*="/magazine/"]')
        if magazine_tag:
            magazine = magazine_tag.get_text(strip=True)
        else:
            publisher_tag = soup.select_one('.category_line a[href*="/publisher/"]')
            if publisher_tag:
                magazine = publisher_tag.get_text(strip=True)

        return {
            "synopsis": synopsis,
            # === 変更点: 順番を保持したまま重複を削除 ===
            "genres": list(dict.fromkeys(genres)),
            # =======================================
            "magazine": magazine,
        }
    except requests.exceptions.RequestException as e:
        print(f"URLへのアクセスに失敗しました: {url}, Error: {e}")
        return None
    except Exception as e:
        print(f"スクレイピング中にエラーが発生しました: {e}")
        return None

def main():
    """メイン処理"""
    if not NOTION_API_KEY or not DATABASE_ID:
        print("エラー: 環境変数 NOTION_API_KEY と DATABASE_ID が設定されていません。")
        return
        
    print("Notionデータベースのチェックを開始します...")
    
    target_pages = notion.databases.query(
        database_id=DATABASE_ID,
        filter={
            "and": [
                {"property": "URL", "url": {"is_not_empty": True}},
                {"property": "あらすじ", "rich_text": {"is_empty": True}}
            ]
        }
    )

    if not target_pages["results"]:
        print("処理対象のページは見つかりませんでした。")
        return

    for page in target_pages["results"]:
        page_id = page["id"]
        url = page["properties"]["URL"]["url"]
        title = page["properties"]["タイトル"]["title"][0]["plain_text"]
        
        print(f"処理中: {title} ({url})")

        cmoa_data = scrape_cmoa_data(url)

        if cmoa_data and cmoa_data["synopsis"]:
            try:
                notion.pages.update(
                    page_id=page_id,
                    properties={
                        "あらすじ": {"rich_text": [{"text": {"content": cmoa_data["synopsis"]}}]},
                        "ジャンル": {"multi_select": [{"name": g} for g in cmoa_data["genres"]]},
                        "雑誌・レーベル": {"multi_select": [{"name": m} for m in [cmoa_data["magazine"]] if m]}
                    }
                )
                print(f"✅ {title} の情報を更新しました。")
            except Exception as e:
                print(f"❌ Notionの更新に失敗しました: {e}")

if __name__ == "__main__":
    main()
