.PHONY: test serve
serve:
	python3 -m http.server 8080

test:
	python3 -c "from pathlib import Path; files=[\"index.html\",\"styles.css\",\"app.js\"]; assert all(Path(f).exists() for f in files); html=Path(\"index.html\").read_text(); js=Path(\"app.js\").read_text(); assert all(x in html for x in [\"Simulated data only\",\"id=\\\"chart\\\"\",\"id=\\\"run-button\\\"\"]); assert \"function run\" in js; print(\"AURA-Med Lab smoke test passed\")"
