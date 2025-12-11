.PHONY: build up test enqueue

build:
	docker compose build

up:
	docker compose up

test:
	pytest tests/

enqueue:
	python -m youtube_factory.worker enqueue --topic "$(TOPIC)" --niche "General" --length 480