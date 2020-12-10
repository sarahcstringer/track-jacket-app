lint:
	@echo "Running isort and black"
	@find . -name "*.py" ! -name "*_pb2*" ! -path "./venv/*" -exec isort {} \+ -exec black {} \+
