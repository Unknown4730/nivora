.PHONY: install test build frontend-test frontend-build serve docker-build docker-run

PYTHON_BOOTSTRAP ?= python3.12
PYTHON ?= .venv/bin/python
PYTHONPATH := backend

install:
	$(PYTHON_BOOTSTRAP) -m venv .venv
	.venv/bin/python -m pip install --requirement requirements.lock
	npm --prefix frontend ci

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s backend/tests -p "test_*.py"
	npm --prefix frontend test

build:
	$(PYTHON) -m compileall -q backend
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s backend/tests -p "test_*.py"
	npm --prefix frontend run build

frontend-test:
	npm --prefix frontend ci
	npm --prefix frontend test

frontend-build:
	npm --prefix frontend ci
	npm --prefix frontend run build

serve:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m uvicorn aura_med.api.main:app --host 127.0.0.1 --port $${PORT:-8000}

docker-build:
	docker build --tag aura-med:local .

docker-run:
	docker run --rm --publish 8000:8000 --volume aura-med-data:/app/.runtime aura-med:local
