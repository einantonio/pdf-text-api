from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import io
import os
import zipfile
from pdfminer.high_level import extract_text
from pdfminer.pdfparser import PDFSyntaxError
import mammoth
import PyPDF2
from docx import Document

app = Flask(__name__)
CORS(app)

def fallback_docx(file_content):
    file_content.seek(0)
    try:
        doc = Document(file_content)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        raise ValueError(f"Fallback DOCX parsing failed: {str(e)}")

def is_docx_zip(file_content):
    file_content.seek(0)
    try:
        with zipfile.ZipFile(file_content) as z:
            return 'word/document.xml' in z.namelist()
    except zipfile.BadZipFile:
        return False

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

@app.route('/extract-file', methods=['POST'])
def extract_file():
    data = request.get_json()
    url = data.get('url')

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        response = requests.get(url)
        response.raise_for_status()

        file_content = io.BytesIO(response.content)
        content_type = response.headers.get('Content-Type', '').lower()
        url_lower = url.lower()

        print("Content-Type:", content_type)
        print("URL:", url)

        if 'application/pdf' in content_type or url_lower.endswith('.pdf'):
            pdf_reader = PyPDF2.PdfReader(file_content)
            num_pages = len(pdf_reader.pages)
            file_content.seek(0)
            text = extract_text(file_content)
            file_type = 'pdf'
            stats = {"pages": num_pages}

        elif (
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in content_type
            or url_lower.endswith('.docx')
            or is_docx_zip(file_content)
        ):
            try:
                file_content.seek(0)
                result = mammoth.extract_raw_text(file_content)
                text = result.value
            except Exception:
                text = fallback_docx(file_content)
            file_type = 'docx'
            word_count = len(text.split())
            stats = {"words": word_count}

        else:
            print("Unsupported file type triggered")
            return jsonify({
                "error": "Unsupported file type",
                "debug": {
                    "content_type": content_type,
                    "url": url
                }
            }), 400

        return jsonify({
            "text": text.strip(),
            "info": {
                "type": file_type,
                **stats,
                "length": len(text)
            }
        })

    except PDFSyntaxError:
        return jsonify({"error": "Invalid PDF file"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
#Extraccion de texto vacantes
from bs4 import BeautifulSoup
import time
import requests

APIFY_TOKEN = "apify_api_xGpnABpktLvk8UZK2Q5qLMK1LOLPBw2u5XHo"  # Sustituye por tu token real

@app.route('/extract-job-text', methods=['POST'])
def extract_job_text():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "URL is required"}), 400

    try:
        # Si es sitio dinámico, usa Apify
        if any(domain in url for domain in [
            "linkedin.com", "indeed.com", "glassdoor.com", "computrabajo.com", "occ.com.mx"
        ]):
            extracted_text = extract_with_apify(url)
            return jsonify({"source": "apify", "text": extracted_text})

        # Si es HTML simple, usa BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
            tag.extract()

        text = soup.get_text(separator=' ', strip=True)
        clean = ' '.join(text.split())
        return jsonify({"source": "beautifulsoup", "text": clean[:10000]})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def extract_with_apify(url):
    try:
        task_id = "6hTBPhkVAV9z6wSlU"
        run_url = f"https://api.apify.com/v2/actor-tasks/{task_id}/runs?token={APIFY_TOKEN}"

        payload = {
            "input": {
                "startUrls": [{"url": url}],
                "maxPagesPerCrawl": 1,
                "crawlerType": "cheerio",
                "proxyConfiguration": {"useApifyProxy": True}
            },
            "build": "latest"  # <- esto permite sobreescribir input del task
        }

        # Ejecutar el Task
        run_response = requests.post(run_url, json=payload)
        run_response.raise_for_status()
        run_data = run_response.json()
        run_id = run_data.get("data", {}).get("id")

        if not run_id:
            return "Error: no run ID returned."

        # Polling hasta terminar
        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_TOKEN}"
        for _ in range(30):  # ~45s
            time.sleep(1.5)
            status_response = requests.get(status_url)
            status_data = status_response.json()
            status = status_data.get("data", {}).get("status")
            if status == "SUCCEEDED":
                break
        else:
            return "Error: Apify run did not finish in time."

        # Obtener dataset
        dataset_id = status_data.get("data", {}).get("defaultDatasetId")
        if not dataset_id:
            return "Error: no dataset ID found."

        dataset_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_TOKEN}&format=json"
        dataset_response = requests.get(dataset_url)
        dataset_response.raise_for_status()
        dataset_items = dataset_response.json()

        if not dataset_items:
            return "Error: dataset is empty."

        # Extraer texto útil
        text_parts = []
        for item in dataset_items:
            content = item.get("text") or item.get("html") or item.get("markdown") or ""
            text_parts.append(content)

        combined_text = " ".join(text_parts)
        return ' '.join(combined_text.split())[:10000]

    except Exception as e:
        return f"Error al usar Apify: {str(e)}"




if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
