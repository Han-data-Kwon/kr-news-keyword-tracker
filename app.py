import os
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import urllib.parse
from flask import Flask, request, jsonify, render_template
from datetime import datetime, timedelta
from flask_cors import CORS
from urllib.parse import unquote

app = Flask(__name__)
CORS(app)

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NTS_API_KEY = os.getenv("NTS_API_KEY")
if not NTS_API_KEY:
    raise ValueError("NTS_API_KEY 환경변수가 설정되지 않았습니다.")

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

@app.route("/api/nts", methods=["POST"])
def search_nts_status():
    try:
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "파일이 업로드되지 않았습니다."}), 400

        df = pd.read_excel(file)
        if "사업자등록번호" not in df.columns:
            return jsonify({"error": "'사업자등록번호' 컬럼이 필요합니다."}), 400

        results = []
        for idx, row in df.iterrows():
            biz_no = str(row["사업자등록번호"]).strip().replace("-", "")
            if not biz_no.isdigit() or len(biz_no) != 10:
                results.append({
                    "사업자등록번호": row["사업자등록번호"],
                    "상태": "형식 오류",
                    "과세유형": "-",
                    "폐업일자": "-"
                })
                continue

            # ✅ 국세청 API 호출 샘플 스타일
            url = f"https://api.odcloud.kr/api/nts-businessman/v1/status?serviceKey={NTS_API_KEY}"
            payload = { "b_no": [biz_no] }
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            try:
                response = requests.post(url, headers=headers, json=payload)
                response.raise_for_status()
                json_data = response.json()

                if "data" in json_data and json_data["data"]:
                    item = json_data["data"][0]
                    results.append({
                        "사업자등록번호": biz_no,
                        "상태": item.get("b_stt", "N/A"),
                        "과세유형": item.get("tax_type", "N/A"),
                        "폐업일자": item.get("end_dt", "-") or "-"
                    })
                else:
                    results.append({
                        "사업자등록번호": biz_no,
                        "상태": "조회 실패",
                        "과세유형": "-",
                        "폐업일자": "-"
                    })

            except Exception as api_err:
                print(f"[ERROR] API 요청 실패: {api_err}")
                results.append({
                    "사업자등록번호": biz_no,
                    "상태": "API 호출 실패",
                    "과세유형": "-",
                    "폐업일자": "-"
                })

        return jsonify(results)

    except Exception as e:
        print(f"[ERROR] 전체 처리 실패: {e}")
        return jsonify({"error": f"파일 처리 중 오류 발생: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=True)
