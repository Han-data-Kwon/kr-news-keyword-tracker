import os
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import urllib.parse
from flask import Flask, request, jsonify, render_template
from datetime import datetime, timedelta
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NTS_API_KEY = os.environ.get("NTS_API_KEY")

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
        "display": 10,
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

@app.route('/api/nts', methods=['POST'])
def search_nts_status():
    if 'file' not in request.files:
        return jsonify({"error": "엑셀 파일을 업로드해주세요."}), 400

    file = request.files['file']
    try:
        df = pd.read_excel(file)
        print("✅ 업로드된 컬럼명:", df.columns.tolist())

        if '사업자등록번호' not in df.columns:
            return jsonify({"error": "'사업자등록번호' 컬럼이 없습니다."}), 400

        # 사업자등록번호 전처리
        bno_list = df['사업자등록번호'].astype(str).str.replace("-", "").str.strip()
        bno_list = [bno for bno in bno_list if bno.isdigit() and len(bno) == 10]

        print("📌 정제된 사업자등록번호:", bno_list[:5], "... 총", len(bno_list), "건")
        if not bno_list:
            return jsonify({"error": "유효한 10자리 사업자등록번호가 없습니다."}), 400

        chunk_size = 100
        result_data = []
        url = f"https://api.odcloud.kr/api/nts-businessman/v1/status?serviceKey={urllib.parse.unquote(NTS_API_KEY)}"
        headers = {"Content-Type": "application/json"}

        for i in range(0, len(bno_list), chunk_size):
            chunk = bno_list[i:i + chunk_size]
            payload = {"b_no": chunk}

            print(f"🔗 요청 URL: {url}")
            print(f"📦 요청 Payload: {payload}")

            try:
                res = requests.post(url, headers=headers, json=payload)
            except Exception as e:
                print("🚨 API 호출 예외:", e)
                return jsonify({"error": "API 호출 실패", "detail": str(e)}), 500

            print("📥 응답 상태:", res.status_code)
            print("📥 응답 내용:", res.text)

            if res.status_code != 200:
                return jsonify({"error": f"API 오류: {res.status_code}", "detail": res.text}), 500

            try:
                items = res.json().get("data", [])
            except Exception as e:
                print("❌ JSON 디코딩 실패:", e)
                print("❌ 응답 원문:", res.text)
                return jsonify({"error": "API 응답이 올바르지 않습니다.", "detail": str(e)}), 500

            for item in items:
                result_data.append({
                    "사업자등록번호": item.get("b_no"),
                    "상태": item.get("b_stt"),
                    "과세유형": item.get("tax_type"),
                    "폐업일자": item.get("end_dt", "")
                })

        return jsonify(result_data)

    except Exception as e:
        print("🚨 전체 예외 발생:", str(e))
        return jsonify({"error": "파일 처리 또는 API 호출 중 오류 발생", "detail": str(e)}), 500


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=True)
