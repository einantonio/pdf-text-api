from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import io
import os
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

        if 'application/pdf' in content_type or url.endswith('.pdf'):
            pdf_reader = PyPDF2.PdfReader(file_content)
            num_pages = len(pdf_reader.pages)
            file_content.seek(0)
            text = extract_text(file_content)
            file_type = 'pdf'
            stats = {"pages": num_pages}

        elif 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in content_type or url.endswith('.docx'):
            try:
                result = mammoth.extract_raw_text(file_content)
                text = result.value
            except Exception:
                text = fallback_docx(file_content)
            file_type = 'docx'
            word_count = len(text.split())
            stats = {"words": word_count}

        else:
            return jsonify({"error": "Unsupported file type"}), 400

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
