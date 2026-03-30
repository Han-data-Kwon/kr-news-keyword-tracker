import os
import json
import ssl
import requests
import urllib3
import pandas as pd
from flask import Flask, request, jsonify, render_template
from datetime import datetime, timedelta
from flask_cors import CORS
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LegacyDHAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.set_ciphers("DEFAULT:@SECLEVEL=1")
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=context,
            **pool_kwargs,
        )

_dart_session = requests.Session()
_dart_session.mount("https://", LegacyDHAdapter())
_dart_session.mount("http://", LegacyDHAdapter())

app = Flask(__name__)
CORS(app)

NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NTS_API_KEY         = os.getenv("NTS_API_KEY")
NPS_API_KEY         = os.getenv("NPS_API_KEY", "6eb71aa2822504015095fc5fcab3fa15faabcd5e55f8d96a9fbe7edc0514cb73")
DART_API_KEY        = os.getenv("DART_API_KEY", "3246eba1857c0b107dcc21c6e30136045a8d7ff3")


# ─────────────────────────────────────────────
# 공통 라우트
# ─────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("index.html")


# ─────────────────────────────────────────────
# 뉴스 검색
# ─────────────────────────────────────────────
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
    params = {"query": keyword, "display": 10, "sort": "date"}

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json().get("items", [])
        return jsonify([{
            "title": item.get("title", "").replace("<b>", "").replace("</b>", ""),
            "link": item.get("link"),
            "source": item.get("originallink") or item.get("link"),
            "date": item.get("pubDate", "")
        } for item in data])
    except Exception as e:
        print("NAVER 뉴스 API 오류:", e)
        return jsonify([])


# ─────────────────────────────────────────────
# 네이버 데이터랩 트렌드
# ─────────────────────────────────────────────
@app.route("/api/trend")
def get_trend():
    keyword = request.args.get("q")
    period  = request.args.get("period", "30d")
    if not keyword:
        return jsonify({"error": "Missing keyword"}), 400

    end_date   = datetime.today()
    start_date = end_date - timedelta(days=365 if period == "1y" else 30)

    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json"
    }
    payload = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate":   end_date.strftime("%Y-%m-%d"),
        "timeUnit": "date",
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}]
    }

    try:
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        data = res.json()
        return jsonify([{"date": d["period"], "ratio": d["ratio"]} for d in data["results"][0]["data"]])
    except Exception as e:
        print("트렌드 API 오류:", e)
        return jsonify({"error": "Failed to fetch trend"}), 500


# ─────────────────────────────────────────────
# 기업 검색 통합 엔드포인트
# ─────────────────────────────────────────────
@app.route("/api/company/search")
def company_search():
    keyword     = request.args.get("q", "").strip()
    search_type = request.args.get("type", "all")

    print(f"[SEARCH CALLED] keyword={keyword}, type={search_type}")  # 추가

    if not keyword:
        return jsonify({"error": "검색어를 입력해주세요."}), 400

    dart_results = []
    nps_results  = []

    print("[SEARCH] dart 시작")  # 추가
    if search_type in ("all", "dart"):
        dart_results = _search_dart(keyword)
    print(f"[SEARCH] dart 완료: {len(dart_results)}건")  # 추가

    print("[SEARCH] nps 시작")  # 추가
    if search_type in ("all", "nps"):
        nps_results = _search_nps(keyword)
    print(f"[SEARCH] nps 완료: {len(nps_results)}건")  # 추가

    return jsonify({
        "dart": dart_results,
        "nps":  nps_results
    })


# ─────────────────────────────────────────────
# DART 기업 상세
# ─────────────────────────────────────────────
@app.route("/api/company/dart/detail")
def dart_detail():
    corp_code = request.args.get("corp_code", "").strip()
    if not corp_code:
        return jsonify({"error": "corp_code 필요"}), 400

    info    = _fetch_dart_company_info(corp_code)
    finance = _fetch_dart_finance(corp_code)

    return jsonify({**info, **finance})


# ─────────────────────────────────────────────
# NTS 사업자 상태 조회
# ─────────────────────────────────────────────
@app.route("/api/company/nts")
def company_nts():
    b_no_raw = request.args.get("b_no", "").strip()
    b_no     = b_no_raw.replace("-", "").zfill(10)

    if not b_no.isdigit() or len(b_no) != 10:
        return jsonify({"error": "사업자등록번호 형식 오류 (10자리)"}), 400

    return jsonify(_fetch_nts(b_no))


# ─────────────────────────────────────────────
# 헬퍼: DART 회사 검색
# ─────────────────────────────────────────────
def _search_dart(keyword: str) -> list:
    # DART 전체 기업 목록 다운로드 후 키워드 필터
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    try:
        res = _dart_session.get(url, params={
            "crtfc_key": DART_API_KEY
        }, timeout=15, verify=False)
        res.raise_for_status()

        # zip 압축 해제
        import zipfile
        import io
        import xml.etree.ElementTree as ET

        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            xml_filename = z.namelist()[0]
            with z.open(xml_filename) as f:
                tree = ET.parse(f)
                root = tree.getroot()

        results = []
        for item in root.findall("list"):
            corp_name = item.findtext("corp_name", "")
            if keyword.lower() in corp_name.lower():
                results.append({
                    "corp_code":  item.findtext("corp_code", "-"),
                    "corp_name":  corp_name,
                    "stock_code": item.findtext("stock_code", "-") or "-",
                    "corp_cls":   _corp_cls_label(item.findtext("corp_cls", "")),
                    "jurir_no":   "-",
                    "bizr_no":    "-",
                    "source":     "DART"
                })
            if len(results) >= 10:
                break

        print(f"[DART DEBUG] 검색결과: {len(results)}건")
        return results

    except Exception as e:
        print(f"[DART SEARCH ERROR] {e}")
        return []

# ─────────────────────────────────────────────
# 헬퍼: DART 기업 기본정보
# ─────────────────────────────────────────────
def _fetch_dart_company_info(corp_code: str) -> dict:
    url = "https://opendart.fss.or.kr/api/company.json"
    try:
        res = _dart_session.get(url, params={
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code
        }, timeout=7, verify=False)
        res.raise_for_status()
        d = res.json()
        if d.get("status") != "000":
            return {}
        result = {
            "corp_name":     d.get("corp_name"),
            "corp_name_eng": d.get("corp_name_eng", "-"),
            "stock_code":    d.get("stock_code") or "-",
            "ceo_nm":        d.get("ceo_nm", "-"),
            "corp_cls":      _corp_cls_label(d.get("corp_cls")),
            "jurir_no":      d.get("jurir_no", "-"),
            "bizr_no":       d.get("bizr_no", "-"),
            "adres":         d.get("adres", "-"),
            "hm_url":        d.get("hm_url", "-"),
            "ir_url":        d.get("ir_url", "-"),
            "phn_no":        d.get("phn_no", "-"),
            "induty_code":   d.get("induty_code", "-"),
            "est_dt":        d.get("est_dt", "-"),
            "acc_mt":        d.get("acc_mt", "-"),
        }
        # 임직원수 추가 조회
        result["emp_count"] = _fetch_dart_emp(corp_code)
        return result
    except Exception as e:
        print(f"[DART INFO ERROR] {e}")
        return {}


def _fetch_dart_emp(corp_code: str) -> str:
    url = "https://opendart.fss.or.kr/api/empSttus.json"
    year = str(datetime.today().year - 1)
    try:
        res = _dart_session.get(url, params={
            "crtfc_key":  DART_API_KEY,
            "corp_code":  corp_code,
            "bsns_year":  year,
            "reprt_code": "11011"  # 사업보고서
        }, timeout=7, verify=False)
        res.raise_for_status()
        data = res.json()
        if data.get("status") != "000":
            return "-"
        total = 0
        for item in data.get("list", []):
            try:
                cnt = item.get("reform_coexist_nmpr") or item.get("fo_bbm") or "0"
                total += int(str(cnt).replace(",", ""))
            except:
                continue
        return str(total) if total > 0 else "-"
    except Exception as e:
        print(f"[DART EMP ERROR] {e}")
        return "-"

# ─────────────────────────────────────────────
# 헬퍼: DART 재무정보
# ─────────────────────────────────────────────
def _fetch_dart_finance(corp_code: str) -> dict:
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    year = str(datetime.today().year - 1)
    try:
        res = _dart_session.get(url, params={
            "crtfc_key":  DART_API_KEY,
            "corp_code":  corp_code,
            "bsns_year":  year,
            "reprt_code": "11011",
            "fs_div":     "CFS"
        }, timeout=10, verify=False)
        res.raise_for_status()
        data = res.json()
        if data.get("status") != "000":
            return {"finance": []}

        targets = {"매출액", "영업이익", "당기순이익", "자본총계", "부채총계", "자산총계"}
        rows = []
        for item in data.get("list", []):
            if item.get("account_nm") in targets and item.get("sj_div") in ("IS", "BS"):
                rows.append({
                    "항목": item.get("account_nm"),
                    "당기": item.get("thstrm_amount", "-"),
                    "전기": item.get("frmtrm_amount", "-"),
                    "단위": "원"
                })
        return {"finance": rows, "finance_year": year}
    except Exception as e:
        print(f"[DART FINANCE ERROR] {e}")
        return {"finance": [], "finance_year": year}


# ─────────────────────────────────────────────
# 헬퍼: NPS 사업장 검색
# ─────────────────────────────────────────────
def _search_nps(keyword: str) -> list:
    url = "https://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2/getBassInfoSearchV2"
    try:
        res = _dart_session.get(url, params={
            "serviceKey": NPS_API_KEY,
            "wkplNm":     keyword,
            "dataType":   "json",
            "pageNo":     1,
            "numOfRows":  10
        }, timeout=20, verify=False)
        res.raise_for_status()
        print(f"[NPS DEBUG] status_code={res.status_code}, raw={res.text[:300]}")

        data = res.json()
        items = data.get("items", {})
        if isinstance(items, dict):
            item_list = items.get("item", [])
        else:
            item_list = items
        if isinstance(item_list, dict):
            item_list = [item_list]

        return [{
            "사업장명":       d.get("wkplNm", "-"),
            "사업자등록번호": d.get("bzowrRgstNo", "-"),
            "가입자수":       d.get("totMnbscNpc", "-"),
            "주소":           d.get("wkplAddr", "-"),
            "업종":           d.get("ndbizNm", "-"),
            "source":         "NPS"
        } for d in item_list]

    except requests.exceptions.Timeout:
        print(f"[NPS TIMEOUT] 응답 지연으로 조회 실패")
        return []
    except Exception as e:
        print(f"[NPS SEARCH ERROR] {e}")
        return []

# ─────────────────────────────────────────────
# 헬퍼: NTS 사업자 상태 단건
# ─────────────────────────────────────────────
def _fetch_nts(b_no: str) -> dict:
    if not NTS_API_KEY:
        return {"error": "NTS_API_KEY 미설정"}
    url = f"https://api.odcloud.kr/api/nts-businessman/v1/status?serviceKey={NTS_API_KEY}"
    try:
        res = _dart_session.post(url,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"b_no": [b_no]}, timeout=5, verify=False)
        res.raise_for_status()
        data = res.json().get("data", [])
        return data[0] if data else {}
    except Exception as e:
        print(f"[NTS ERROR] {e}")
        return {}


def _corp_cls_label(cls: str) -> str:
    return {"Y": "유가증권(KOSPI)", "K": "코스닥(KOSDAQ)", "N": "코넥스", "E": "기타(비상장)"}.get(cls or "", cls or "-")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
