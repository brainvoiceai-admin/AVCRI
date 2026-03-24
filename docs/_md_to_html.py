"""One-off: build client handbook HTML for Google Docs import."""
import markdown

MD_PATH = r"c:\Users\jaise\OneDrive\Desktop\git\AVCRI\docs\KT_AVCRI_Client_Handbook_Complete.md"
OUT_PATH = r"c:\Users\jaise\OneDrive\Desktop\git\AVCRI\docs\KT_AVCRI_Client_Handbook_Complete.html"

CSS = """
body { font-family: Arial, Helvetica, sans-serif; max-width: 900px; margin: 2em auto; line-height: 1.5; color: #222; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 14px; }
th, td { border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; }
th { background: #f5f5f5; }
h1, h2, h3, h4 { margin-top: 1.3em; }
code { background: #f4f4f4; padding: 2px 5px; font-size: 0.95em; }
hr { margin: 2em 0; border: none; border-top: 1px solid #ddd; }
"""

def main():
    md = open(MD_PATH, encoding="utf-8").read()
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "nl2br"])
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AVCRI — Client Knowledge Transfer Handbook</title>
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>"""
    open(OUT_PATH, "w", encoding="utf-8").write(doc)
    print("Wrote", OUT_PATH)

if __name__ == "__main__":
    main()
