HELM ?= helm
PYTHON ?= python3

.PHONY: lint test check package
lint:
	$(HELM) lint standard --strict -f examples/api.values.yaml
	$(HELM) lint standard --strict -f examples/worker.values.yaml
	$(HELM) lint standard --strict -f examples/api.values.yaml -f examples/traefik-tls.values.yaml -f examples/monitoring.values.yaml -f examples/autoscaling.values.yaml
	$(HELM) lint standard --strict -f examples/api.values.yaml -f examples/persistence.values.yaml
	$(HELM) lint standard --strict -f examples/api.values.yaml --set pdb.enabled=true --set pdb.minAvailable=0

test:
	$(PYTHON) -m unittest discover -s tests -v

check: lint test

package:
	mkdir -p dist
	$(HELM) package standard --destination dist
