.PHONY: install seed backend frontend demo test evaluate

install:
	pip install -r requirements.txt
	cd strain/frontend && npm install

seed:
	python scripts/seed_corpus.py

backend:
	uvicorn strain.backend.main:app --reload --port 8000

frontend:
	cd strain/frontend && npm run dev

demo:
	python scripts/seed_corpus.py
	start /B uvicorn strain.backend.main:app --reload --port 8000
	cd strain/frontend && npm run dev

test:
	pytest tests/ -v --cov=strain/backend/pipeline --cov-report=term-missing

evaluate:
	python scripts/evaluate.py
