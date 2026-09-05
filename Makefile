COMPOSE := docker compose
PYTHON ?= python

.PHONY: up up-all down logs seed demo-reset test fmt clean

up:
	$(COMPOSE) up --detach --build --wait --wait-timeout 120

up-all:
	$(COMPOSE) --profile app up --detach --build --wait --wait-timeout 120

down:
	$(COMPOSE) --profile app down --volumes --remove-orphans

logs:
	$(COMPOSE) --profile app logs --follow

seed:
	$(PYTHON) scripts/seed_local.py

demo-reset:
	$(PYTHON) scripts/demo_reset.py

test:
	$(PYTHON) -m pytest mock-services/bank mock-services/merchant

fmt:
	$(PYTHON) -m ruff format mock-services/bank mock-services/merchant scripts
	terraform fmt -recursive infrastructure

clean:
	$(COMPOSE) --profile app down --volumes --remove-orphans --rmi local
