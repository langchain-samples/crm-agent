.PHONY: dev deploy

dev:
	uv run langgraph dev

deploy:
	uv run langgraph deploy
