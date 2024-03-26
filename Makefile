.PHONY: dev-reformat

dev-reformat:
	poetry run ruff check arbitrage --fix
	poetry run ruff format arbitrage

dev-type-check:
	poetry run mypy arbitrage
