"""Inline ucl/model.js and a model export into web/ucl_template.html -> ucl.html.

    python ucl/build_page.py data/ucl_model_2026-10-21.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data_path = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted((ROOT / "data").glob("ucl_model_*.json"))[-1]
data = json.loads((ROOT / data_path).read_text(encoding="utf-8")) if not data_path.is_absolute() else json.loads(data_path.read_text(encoding="utf-8"))
tpl = (ROOT / "web" / "ucl_template.html").read_text(encoding="utf-8")
model = (ROOT / "ucl" / "model.js").read_text(encoding="utf-8")
html = tpl.replace("/*__MODEL_JS__*/", model).replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
(ROOT / "ucl.html").write_text(html, encoding="utf-8")
print(f"ucl.html {len(html)} bytes from {data_path}")
