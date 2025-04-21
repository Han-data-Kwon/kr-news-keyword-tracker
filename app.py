from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/search_news")
def search_news():
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify([])

    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    url = f"https://www.google.com/search?q={keyword}+site:.kr&tbm=nws&hl=ko"
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    for g in soup.select("div.dbsr")[:5]:
        title = g.select_one("div.JheGif.nDgy9d")
        link = g.a["href"]
        source = g.select_one(".XTjFC.WF4CUc")
        date = g.select_one(".WG9SHc span")

        results.append({
            "title": title.text if title else "",
            "link": link,
            "source": source.text if source else "",
            "date": date.text if date else ""
        })

    return jsonify(results)

# ✅ Render 환경을 위한 포트 바인딩
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)