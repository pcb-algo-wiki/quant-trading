# 开发常用任务（Linux/macOS / Git Bash）
# Windows 用户请使用 scripts/dev.ps1
.PHONY: install test test-cov lint pipeline help

help:
	@echo "Tasks: install | test | test-cov | lint | pipeline"

install:
	python -m pip install --upgrade pip
	python -m pip install -r requirements.txt

test:
	python -m pytest -q

test-cov:
	python -m pytest --cov=. --cov-report=term-missing

lint:
	@find data strategies backtest execution knowledge research ml data_store utils scripts \
		-name '*.py' -print0 | xargs -0 -n1 python -m py_compile
	@echo "py_compile OK"

pipeline:
	python run.py --daily-pipeline
