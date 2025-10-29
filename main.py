import os
import requests
import json
import time
import sys
import io
from bs4 import BeautifulSoup
from notion_client import Client

# 文字エンコーディングの問題を解決
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- 設定項目 (GitHub Secretsから読み込む) ---
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("DATABASE_ID")

# Notionクライアントの初期化
try:
    notion = Client(auth=NOTION_API_KEY)
    print("Notionクライアントの初期化が完了しました。")
except Exception as e:
    print(f"Notionクライアントの初期化に失敗しました: {e}")
    exit(1)

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

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. あらすじ取得
        synopsis = ""
        script_tag = soup.find("script", type="application/ld+json")
        if script_tag:
            try:
                clean_string = script_tag.string.encode('utf-8').decode('utf-8')
                json_data = json.loads(clean_string)
                synopsis = json_data.get("description", "")
            except Exception:
                synopsis = ""

        if not synopsis:
            description_div = soup.select_one("div#comic_description p")
            if description_div:
                for br in description_div.find_all("br"):
                    br.replace_with("\n")
                synopsis = description_div.get_text()

        synopsis = synopsis.replace("<br>", "\n")
        for phrase in exclusion_phrases:
            synopsis = synopsis.replace(phrase, "")
        synopsis = synopsis.strip()

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
        
        # 4. 作品タグ取得
        tags = []
        # === 変更点: ご提示のHTML構造に合わせた最終ロジック ===
        # 「作品タグ」というテキストを持つdivを探す
        tag_label_div = soup.find('div', class_='category_line_f_l_l', string='作品タグ')
        if tag_label_div:
            # その親をたどり、タグのリンクが入っているdivを探す
            tag_container_div = tag_label_div.find_next_sibling('div', class_='category_line_f_r_l')
            if tag_container_div:
                # コンテナ内の全てのaタグ(リンク)を取得
                tag_elements = tag_container_div.find_all('a')
                for tag_element in tag_elements:
                    tags.append(tag_element.get_text(strip=True))
        # =======================================================

        return {
            "synopsis": synopsis,
            "genres": list(dict.fromkeys(genres)),
            "magazine": magazine,
            "tags": list(dict.fromkeys(tags))
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
    
    try:
        # データベースの存在確認
        print(f"データベースID: {DATABASE_ID}")
        
        # データベースクエリを実行
        print("データベースクエリを実行中...")
        target_pages = notion.databases.query(
            database_id=DATABASE_ID,
            filter={
                "and": [
                    {"property": "URL", "url": {"is_not_empty": True}},
                    {"property": "あらすじ", "rich_text": {"is_empty": True}}
                ]
            }
        )
        print(f"データベースクエリが成功しました。対象ページ数: {len(target_pages.get('results', []))}")
        
    except AttributeError as e:
        print(f"AttributeError: {e}")
        print("databases.queryメソッドが利用できません。利用可能なメソッドを確認します。")
        print(f"利用可能なメソッド: {[method for method in dir(notion.databases) if not method.startswith('_')]}")
        
        # 代替手段として、データベース情報を取得してプロパティを確認
        print("代替手段として、データベース情報を取得します...")
        try:
            db_info = notion.databases.retrieve(database_id=DATABASE_ID)
            print("データベース情報の取得に成功しました。")
            print(f"データベースタイトル: {db_info.get('title', [{}])[0].get('plain_text', 'N/A')}")
            print(f"利用可能なプロパティ: {list(db_info.get('properties', {}).keys())}")
            
            # プロパティの詳細を確認
            properties = db_info.get('properties', {})
            if 'URL' in properties:
                print(f"URLプロパティのタイプ: {properties['URL'].get('type')}")
            if 'あらすじ' in properties:
                print(f"あらすじプロパティのタイプ: {properties['あらすじ'].get('type')}")
            
            # 基本的なクエリを再試行
            print("基本的なクエリを再試行します...")
            target_pages = notion.databases.query(database_id=DATABASE_ID, page_size=5)
            print(f"基本クエリが成功しました。取得ページ数: {len(target_pages.get('results', []))}")
            
        except Exception as fallback_error:
            print(f"代替手段でもエラーが発生しました: {fallback_error}")
            return
    except Exception as e:
        print(f"データベースクエリでエラーが発生しました: {e}")
        return

    if not target_pages["results"]:
        print("処理対象のページは見つかりませんでした。")
        return

    print(f"\n処理対象のページ数: {len(target_pages['results'])}")
    
    for i, page in enumerate(target_pages["results"], 1):
        page_id = page["id"]
        url = page["properties"]["URL"]["url"]
        title = page["properties"]["タイトル"]["title"][0]["plain_text"]

        print(f"\n[{i}/{len(target_pages['results'])}] 処理中: {title}")
        print(f"URL: {url}")

        cmoa_data = scrape_cmoa_data(url)

        if cmoa_data and cmoa_data["synopsis"]:
            print(f"取得したデータ:")
            print(f"  あらすじ: {cmoa_data['synopsis'][:100]}...")
            print(f"  ジャンル: {cmoa_data['genres']}")
            print(f"  雑誌・レーベル: {cmoa_data['magazine']}")
            print(f"  タグ: {cmoa_data['tags']}")
            
            try:
                properties_to_update = {
                    "あらすじ": {"rich_text": [{"text": {"content": cmoa_data["synopsis"]}}]},
                    "ジャンル": {"multi_select": [{"name": g} for g in cmoa_data["genres"]]},
                    "雑誌・レーベル": {"multi_select": [{"name": m} for m in [cmoa_data["magazine"]] if m]},
                    "タグ": {"multi_select": [{"name": t} for t in cmoa_data["tags"]]}
                }

                notion.pages.update(
                    page_id=page_id,
                    properties=properties_to_update
                )
                print(f"成功: {title} の情報を更新しました。")
            except Exception as e:
                print(f"Notionの更新に失敗しました: {e}")
        else:
            print(f"データ取得に失敗またはあらすじが空です。")

        # 次のリクエストまで3秒待機
        time.sleep(3)
    
    print(f"\n処理が完了しました。{len(target_pages['results'])}件のページを処理しました。")

if __name__ == "__main__":
    main()
