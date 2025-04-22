import os
import requests
from flask import Flask, request, jsonify, render_template
from datetime import datetime, timedelta
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# 환경변수에서 Client ID / Secret 불러오기 (Render 환경 변수 또는 .env)
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# --- 메인 페이지 ---
@app.route("/")
def home():
    return render_template("index.html")

# --- 네이버 뉴스 검색 API ---
@app.route("/api/search_news")
def search_news():
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify([])

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {
        "query": keyword,
        "display": 5,
        "sort": "date"
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json().get("items", [])

        results = []
        for item in data:
            results.append({
                "title": item.get("title", "").replace("<b>", "").replace("</b>", ""),
                "link": item.get("link"),
                "source": item.get("originallink") or item.get("link"),
                "date": item.get("pubDate", "")
                # 네이버 뉴스 API에서는 description 필드가 제공되지 않을 수 있음.
            })
        return jsonify(results)

    except Exception as e:
        print("NAVER 뉴스 API 오류:", e)
        return jsonify([])

# --- 네이버 데이터랩 검색어 트렌드 API ---
@app.route("/api/trend")
def get_trend():
    keyword = request.args.get("q")
    period = request.args.get("period", "30d")  # 기본 30일, "1y" 옵션 등

    if not keyword:
        return jsonify({"error": "Missing keyword"}), 400

    # 날짜 계산 (기본 최근 30일 또는 최근 1년)
    end_date = datetime.today()
    if period == "1y":
        start_date = end_date - timedelta(days=365)
    else:
        start_date = end_date - timedelta(days=30)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json"
    }
    payload = {
        "startDate": start_str,
        "endDate": end_str,
        "timeUnit": "date",
        "keywordGroups": [
            {
                "groupName": keyword,
                "keywords": [keyword]
            }
        ]
    }

    try:
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        data = res.json()
        # 데이터랩 API는 'results' 키에 결과가 있으며, 첫 그룹의 'data'에 날짜별 검색 비율 정보가 있음
        result = [{"date": d["period"], "ratio": d["ratio"]} for d in data["results"][0]["data"]]
        return jsonify(result)

    except Exception as e:
        print("네이버 데이터랩 트렌드 API 오류:", e)
        return jsonify({"error": "Failed to fetch trend"}), 500

# --- 앱 실행 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)