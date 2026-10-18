.PHONY: test build serve

test:
	npm test

build:
	npm run build

serve:
	python3 -m http.server 8080
