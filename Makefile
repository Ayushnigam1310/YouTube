.PHONY: build up test enqueue

build:
	docker compose build

up:
	docker compose up

test:
	pytest tests/

enqueue:
	# TODO: Implement a script or curl command to enqueue a job
	@echo "Enqueue task not implemented yet."
