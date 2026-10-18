.PHONY: install test build serve

PYTHON_BOOTSTRAP ?= python3.12
PYTHON ?= .venv/bin/python
PYTHONPATH := backend

install:
	$(PYTHON_BOOTSTRAP) -m venv .venv
	.venv/bin/python -m pip install --requirement requirements.lock

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s backend/tests -p "test_*.py"

build:
	$(PYTHON) -m compileall -q backend
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s backend/tests -p "test_*.py"

serve:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m uvicorn aura_med.api.main:app --host 127.0.0.1 --port $${PORT:-8000}
