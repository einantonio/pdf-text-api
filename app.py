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
#extraer vacante
from bs4 import BeautifulSoup
import time
import requests
import re
import os

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

APIFY_TOKEN = "apify_api_xGpnABpktLvk8UZK2Q5qLMK1LOLPBw2u5XHo"  # Coloca tu token real

@app.route('/extract-job-text', methods=['POST'])
def extract_job_text():
    try:
        data = request.get_json()
        url = data.get("url")

        if not url:
            return jsonify({"error": "URL is required"}), 400

        if any(domain in url for domain in ["linkedin.com", "indeed.com", "glassdoor.com", "computrabajo.com", "occ.com.mx"]):
            extracted_result = extract_with_apify(url)
            return jsonify({"source": "apify", **extracted_result})

        # Fallback BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
            tag.extract()

        text = soup.get_text(separator=' ', strip=True)
        clean = ' '.join(text.split())
        return jsonify({"source": "beautifulsoup", "text": clean[:10000], "job_title": "No especificado"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def extract_with_apify(url):
    try:
        if not APIFY_TOKEN or "apify_api_" not in APIFY_TOKEN:
            return {"error": "Apify token no válido o no configurado."}

        task_id = "0EUMhRKPGrYJav7cf"  # ID de tu Task en Apify
        run_url = f"https://api.apify.com/v2/actor-tasks/{task_id}/runs?token={APIFY_TOKEN}"

        payload = {
            "startUrls": [
                { "url": url }
            ],
            "maxPagesPerCrawl": 1
        }

        run_response = requests.post(run_url, json=payload)
        run_response.raise_for_status()
        run_data = run_response.json()
        run_id = run_data.get("data", {}).get("id")

        if not run_id:
            return {"error": "No run ID returned."}

        # Polling hasta que finalice
        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_TOKEN}"
        for _ in range(60):  # Hasta 90 segundos
            time.sleep(1.5)
            status_response = requests.get(status_url)
            status_data = status_response.json()
            if status_data.get("data", {}).get("status") == "SUCCEEDED":
                break
        else:
            return {"error": "Apify run did not finish in time."}

        dataset_id = status_data.get("data", {}).get("defaultDatasetId")
        if not dataset_id:
            return {"error": "No dataset ID found."}

        dataset_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_TOKEN}&format=json"
        dataset_response = requests.get(dataset_url)
        dataset_response.raise_for_status()
        dataset_items = dataset_response.json()

        if not dataset_items:
            return {"error": "Dataset is empty."}

        text_parts = []
        job_title = ""

        for item in dataset_items:
            content = item.get("text") or item.get("html") or item.get("markdown") or ""
            text_parts.append(content)

            job_title = item.get("job_title", "")
            if job_title:
                break

            html_content = item.get("html", "")
            if html_content:
                soup = BeautifulSoup(html_content, "html.parser")
                
                # 1. Buscamos según el dominio
                if "occ.com.mx" in url:
                     job_title_tag = soup.find("p", class_=lambda c: c and any("title" in cls.lower() for cls in (c if isinstance(c, list) else c.split())))
                elif "computrabajo.com" in url or "indeed.com" in url:
                    job_title_tag = soup.find("h1")
                else:
                    # Fallback genérico
                    job_title_tag = soup.find("h1") or soup.find("title")
                
                if job_title_tag:
                    job_title = job_title_tag.get_text(strip=True)
                    break

        combined_text = " ".join(text_parts)
        cleaned_text = ' '.join(combined_text.split())[:10000]

        if not job_title and cleaned_text:
            lines = cleaned_text.splitlines()
            for line in lines[:10]:
                match = re.search(r"(?:Puesto|Vacante|Cargo|Tipo de puesto):\s*(.*)", line, re.IGNORECASE)
                if match:
                    job_title = match.group(1).strip()
                    break

        return {
            "text": cleaned_text,
            "job_title": job_title or "No especificado"
        }

    except Exception as e:
        return {"error": f"Error al usar Apify: {str(e)}"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
