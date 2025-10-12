.PHONY: help install install-dev test lint format check clean pre-commit docker-build docker-run

help:  ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Install production dependencies
	pip install -r requirements.txt

install-dev:  ## Install development dependencies
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

test:  ## Run tests with coverage
	pytest tests/ -v --cov=. --cov-report=term-missing --cov-report=html

test-fast:  ## Run tests without coverage
	pytest tests/ -v

lint:  ## Run linting checks (ruff + black check)
	ruff check .
	black --check .

lint-fix:  ## Run linting with auto-fix
	ruff check . --fix
	black .
	isort .

format:  ## Format code with black and isort
	black .
	isort .

check: lint test  ## Run all checks (lint + test)

security:  ## Run security checks
	safety check
	bandit -r . -f screen

pre-commit-install:  ## Install pre-commit hooks
	pre-commit install
	@echo "✅ Pre-commit hooks installed"

pre-commit:  ## Run pre-commit on all files
	pre-commit run --all-files

pre-commit-update:  ## Update pre-commit hooks
	pre-commit autoupdate

clean:  ## Clean temporary files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name ".coverage" -delete
	rm -rf htmlcov/ .pytest_cache/ .ruff_cache/ build/ dist/ *.egg-info/
	@echo "✅ Cleaned temporary files"

docker-build:  ## Build Docker image
	docker build -t marketplace-news-bot:latest .

docker-build-test:  ## Build and test Docker image
	docker build -t marketplace-news-bot:test .
	docker run --rm marketplace-news-bot:test python -c "import database.db; import services.gemini_client; print('✅ Imports OK')"

docker-run:  ## Run Docker container
	docker compose up -d

docker-logs:  ## Show Docker logs
	docker compose logs -f

docker-stop:  ## Stop Docker containers
	docker compose down

run-listener:  ## Run Telegram listener
	python main.py listener

run-processor:  ## Run marketplace processor
	python main.py processor

run-status:  ## Send status report
	python test_status.py

db-backup:  ## Backup database
	@mkdir -p backups
	@cp data/marketplace_news.db backups/marketplace_news_$(shell date +%Y%m%d_%H%M%S).db
	@echo "✅ Database backed up to backups/"

db-stats:  ## Show database statistics
	sqlite3 data/marketplace_news.db "SELECT 'Channels: ' || COUNT(*) FROM channels; SELECT 'Messages: ' || COUNT(*) FROM raw_messages; SELECT 'Published: ' || COUNT(*) FROM published;"

coverage-report:  ## Generate and open coverage report
	pytest tests/ --cov=. --cov-report=html
	@echo "Opening coverage report..."
	@python -m webbrowser htmlcov/index.html || open htmlcov/index.html || xdg-open htmlcov/index.html

ci-local:  ## Run CI checks locally
	@echo "Running CI checks locally..."
	@make lint
	@make test
	@make security
	@echo "✅ All CI checks passed!"
