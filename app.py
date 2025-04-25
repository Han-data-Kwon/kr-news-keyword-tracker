import os
import requests
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify, render_template
from datetime import datetime, timedelta
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NPS_API_KEY = os.getenv("NPS_API_KEY")

@app.route("/")
def home():
    return render_template("index.html")

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
            })
        return jsonify(results)

    except Exception as e:
        print("NAVER 뉴스 API 오류:", e)
        return jsonify([])

@app.route("/api/trend")
def get_trend():
    keyword = request.args.get("q")
    period = request.args.get("period", "30d")

    if not keyword:
        return jsonify({"error": "Missing keyword"}), 400

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
        result = [{"date": d["period"], "ratio": d["ratio"]} for d in data["results"][0]["data"]]
        return jsonify(result)

    except Exception as e:
        print("네이버 데이터랩 트렌드 API 오류:", e)
        return jsonify({"error": "Failed to fetch trend"}), 500

@app.route("/api/search_company")
def search_company():
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify([])

    url = "https://apis.data.go.kr/B552015/NpsBplcInfoInqireService/getDetailInfoSearch"
    params = {
        "serviceKey": NPS_API_KEY,
        "wkplNm": keyword,
        "numOfRows": 10,
        "pageNo": 1
    }

    try:
        res = requests.get(url, params=params)
        res.raise_for_status()
        root = ET.fromstring(res.content)

        items = root.findall(".//item")
        results = []

        for item in items:
            data = {
                "사업장명": item.findtext("wkplNm", default=""),
                "업종명": item.findtext("vldtVlKrnNm", default=""),
                "등록일": item.findtext("adptDt", default=""),
                "주소": item.findtext("wkplRoadNmDtlAddr", default=""),
                "가입자수": item.findtext("jnngpCnt", default="")
            }
            results.append(data)

        return jsonify(results)

    except Exception as e:
        print("NPS API 오류:", e)
        return jsonify([])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
