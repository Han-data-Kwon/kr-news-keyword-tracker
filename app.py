from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import os
import xml.etree.ElementTree as ET

app = Flask(__name__)
CORS(app)

# 환경변수
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NPS_API_KEY = os.getenv("NPS_API_KEY")  # 국민연금공단 API 키

@app.route("/")
def home():
    return render_template("index.html")

# --- 국내 뉴스 검색기 API ---
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
        print("NAVER API 오류:", e)
        return jsonify([])

# --- 국민연금공단 사업장 상세정보 API ---
@app.route("/api/search_company")
def search_company():
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify([])

    url = "https://apis.data.go.kr/B090041/openapi/service/NpsBplcInfoInqireService/getDetailInfoSearch"
    params = {
        "serviceKey": NPS_API_KEY,
        "wkplNm": keyword
    }

    try:
        res = requests.get(url, params=params)
        tree = ET.fromstring(res.content)

        items = tree.find(".//items")
        results = []
        if items is not None:
            for item in items.findall("item"):
                results.append({
                    "name": item.findtext("wkplNm", ""),
                    "industry": item.findtext("vldtVlKrnNm", ""),
                    "regDate": item.findtext("adptDt", ""),
                    "joinCount": item.findtext("jnngpCnt", ""),
                    "address": item.findtext("wkplRoadNmDtlAddr", ""),
                    "bizRegNo": item.findtext("bzowrRgstNo", ""),
                    "resignDate": item.findtext("scsnDt", ""),
                    "monthlyFee": item.findtext("crrmmNtcAmt", "")
                })
        return jsonify(results)
    except Exception as e:
        print("국민연금공단 API 오류:", e)
        return jsonify([])

# --- 추후 필요시: 검색 트렌드 연동용 라우터 등 추가 가능 ---

# --- Render 호환 포트 설정 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
