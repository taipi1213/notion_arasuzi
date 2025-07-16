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
        # --- 変更点: 除外フレーズやリネーム用の設定を追加 ---
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
        # ----------------------------------------------

        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. あらすじ
        synopsis = ""
        script_tag = soup.find("script", type="application/ld+json")
        if script_tag:
            clean_string = script_tag.string.encode('utf-8').decode('utf-8')
            json_data = json.loads(clean_string)
            synopsis = json_data.get("description", "")
            
            # --- 変更点: あらすじの整形処理を追加 ---
            synopsis = synopsis.replace("<br>", "\n") # brタグを改行に
            for phrase in exclusion_phrases:
                synopsis = synopsis.replace(phrase, "") # 除外フレーズを削除
            synopsis = synopsis.strip() # 前後の空白を削除
            # ---------------------------------------

        # 2. ジャンル
        genres = []
        genre_tags = soup.select('.category_line_f_r_l a[href*="/genre/"]')
        for tag in genre_tags:
            genre_text = tag.get_text(strip=True)
            
            # --- 変更点: ジャンル名の整形とリネーム処理 ---
            cleaned_genre = genre_text.split('(')[0].strip() # (1位)などを削除
            renamed_genre = genre_rename_map.get(cleaned_genre, cleaned_genre) # リネーム
            genres.append(renamed_genre)
            # ---------------------------------------------
        
        # 3. 雑誌・レーベル
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
            "genres": list(set(genres)),
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
