import os
import json
import ssl
import io
import zipfile
import threading
import time
import xml.etree.ElementTree as ET
import requests
import urllib3
import pandas as pd
import datetime
from flask import Flask, request, jsonify, render_template
from datetime import timedelta
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
DART_API_KEY        = os.getenv("DART_API_KEY", "3246eba1857c0b107dcc21c6e30136045a8d7ff3")

CORP_CODE_CACHE_SECONDS = 60 * 60 * 12

_corp_code_cache = {"fetched_at": 0.0, "companies": []}
_corp_code_lock  = threading.Lock()

def _get_corp_codes() -> list:
    now = time.time()
    with _corp_code_lock:
        if _corp_code_cache["companies"] and now - _corp_code_cache["fetched_at"] < CORP_CODE_CACHE_SECONDS:
            return _corp_code_cache["companies"]
        companies = _download_corp_codes()
        _corp_code_cache["companies"]  = companies
        _corp_code_cache["fetched_at"] = now
        return companies

def _download_corp_codes() -> list:
    try:
        print("[DART CACHE] 기업 목록 다운로드 시작...")
        res = _dart_session.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": DART_API_KEY},
            timeout=30, verify=False
        )
        res.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            xml_name = next((n for n in z.namelist() if n.lower().endswith(".xml")), None)
            with z.open(xml_name) as f:
                root = ET.fromstring(f.read())
        companies = [
            {
                "corp_code":  (item.find("corp_code").text  or "").strip(),
                "corp_name":  (item.find("corp_name").text  or "").strip(),
                "stock_code": (item.find("stock_code").text or "").strip(),
            }
            for item in root.findall("list")
        ]
        print(f"[DART CACHE] 완료: {len(companies):,}개")
        return companies
    except Exception as e:
        print(f"[DART CACHE ERROR] {e}")
        return []

with app.app_context():
    _get_corp_codes()


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
    params = {"query": keyword, "display": 10, "sort": "date"}

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json().get("items", [])
        return jsonify([{
            "title":  item.get("title", "").replace("<b>", "").replace("</b>", ""),
            "link":   item.get("link"),
            "source": item.get("originallink") or item.get("link"),
            "date":   item.get("pubDate", "")
        } for item in data])
    except Exception as e:
        print("NAVER 뉴스 API 오류:", e)
        return jsonify([])


@app.route("/api/trend")
def get_trend():
    keyword = request.args.get("q")
    period  = request.args.get("period", "30d")
    if not keyword:
        return jsonify({"error": "Missing keyword"}), 400

    end_date   = datetime.datetime.today()
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
        "timeUnit":  "date",
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


@app.route("/api/company/search")
def company_search():
    keyword = request.args.get("q", "").strip()
    print(f"[SEARCH CALLED] keyword={keyword}")

    if not keyword:
        return jsonify({"error": "검색어를 입력해주세요."}), 400

    dart_results = _search_dart(keyword)
    print(f"[SEARCH] dart 완료: {len(dart_results)}건")

    return jsonify({"dart": dart_results, "nps": []})


@app.route("/api/company/dart/detail")
def dart_detail():
    corp_code = request.args.get("corp_code", "").strip()
    if not corp_code:
        return jsonify({"error": "corp_code 필요"}), 400

    info    = _fetch_dart_company_info(corp_code)
    finance = _fetch_dart_finance(corp_code)

    return jsonify({**info, **finance})


@app.route("/api/company/nts")
def company_nts():
    b_no_raw = request.args.get("b_no", "").strip()
    b_no     = b_no_raw.replace("-", "").zfill(10)

    if not b_no.isdigit() or len(b_no) != 10:
        return jsonify({"error": "사업자등록번호 형식 오류 (10자리)"}), 400

    return jsonify(_fetch_nts(b_no))


def _search_dart(keyword: str) -> list:
    try:
        corp_list = _get_corp_codes()
        kw = keyword.strip().lower()

        matched = []
        for c in corp_list:
            name = c["corp_name"].lower()
            if kw not in name:
                continue
            matched.append({
                **c,
                "relevance_rank": 0 if name == kw else (1 if name.startswith(kw) else 2),
                "listed_rank":    0 if c["stock_code"] else 1,
            })

        matched.sort(key=lambda x: (x["relevance_rank"], x["listed_rank"], x["corp_name"].lower()))

        results = []
        for c in matched[:15]:
            results.append({
                "corp_code":  c["corp_code"],
                "corp_name":  c["corp_name"],
                "stock_code": c["stock_code"] or "-",
                "source":     "DART"
            })

        print(f"[DART DEBUG] 검색결과: {len(results)}건")
        return results

    except Exception as e:
        print(f"[DART SEARCH ERROR] {e}")
        return []


def _fetch_dart_company_info(corp_code: str) -> dict:
    try:
        res = _dart_session.get(
            "https://opendart.fss.or.kr/api/company.json",
            params={"crtfc_key": DART_API_KEY, "corp_code": corp_code},
            timeout=7, verify=False
        )
        res.raise_for_status()
        d = res.json()
        if d.get("status") != "000":
            return {}
        return {
            "corp_name":     d.get("corp_name", "-"),
            "corp_name_eng": d.get("corp_name_eng", "-"),
            "stock_code":    d.get("stock_code") or "-",
            "ceo_nm":        d.get("ceo_nm", "-"),
            "corp_cls":      _corp_cls_label(d.get("corp_cls")),
            "jurir_no":      d.get("jurir_no", "-"),
            "bizr_no":       d.get("bizr_no", "-"),
            "adres":         d.get("adres", "-"),
            "hm_url":        d.get("hm_url") or "-",
            "phn_no":        d.get("phn_no", "-"),
            "induty_code":   d.get("induty_code", "-"),
            "est_dt":        d.get("est_dt", "-"),
            "acc_mt":        d.get("acc_mt", "-"),
            "emp_count":     _fetch_dart_emp(corp_code),
        }
    except Exception as e:
        print(f"[DART INFO ERROR] {e}")
        return {}


def _fetch_dart_emp(corp_code: str):
    year = str(datetime.date.today().year - 1)
    try:
        res = _dart_session.get(
            "https://opendart.fss.or.kr/api/empSttus.json",
            params={
                "crtfc_key":  DART_API_KEY,
                "corp_code":  corp_code,
                "bsns_year":  year,
                "reprt_code": "11011",
            },
            timeout=7, verify=False
        )
        res.raise_for_status()
        data = res.json()
        if data.get("status") != "000":
            return None
        total = 0
        found = False
        for row in data.get("list", []):
            val = _to_int(row.get("sm", ""))
            if val > 0:
                total += val
                found = True
        return total if found else None
    except Exception as e:
        print(f"[DART EMP ERROR] {e}")
        return None


def _fetch_dart_finance(corp_code: str) -> dict:
    year = str(datetime.date.today().year - 1)
    try:
        res = _dart_session.get(
            "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
            params={
                "crtfc_key":  DART_API_KEY,
                "corp_code":  corp_code,
                "bsns_year":  year,
                "reprt_code": "11011",
                "fs_div":     "CFS"
            },
            timeout=10, verify=False
        )
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
                })
        return {"finance": rows, "finance_year": year}
    except Exception as e:
        print(f"[DART FINANCE ERROR] {e}")
        return {"finance": [], "finance_year": year}


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


def _to_int(value) -> int:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
