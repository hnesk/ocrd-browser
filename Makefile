export

SHELL = /bin/bash
PYTHON = python3
PIP = pip3
LOG_LEVEL = INFO
PYTHONIOENCODING=utf8
SHARE_DIR=~/.local/share
DOCKER_TAG = ocrd_browser

deps-ubuntu:
	apt-get install -o Acquire::Retries=3 --no-install-recommends -y libcairo2-dev libgtk-3-bin libgtk-3-dev libglib2.0-dev libgtksourceview-3.0-dev libgirepository1.0-dev gir1.2-webkit2-4.0 python3-dev pkg-config cmake

deps-dev:
	$(PIP) install -r requirements-dev.txt

deps:
	$(PIP) install -r requirements.txt

install: ocrd_browser/ui.gresource
	$(PIP) install -e .

ocrd_browser/ui.gresource: gresources/ocrd-browser.gresource.xml gresources
	glib-compile-resources --sourcedir=$(<D) --target=$@ $<


install-xdg-mime: share/mime/packages/org.readmachine.ocrd-browser.xml
	mkdir -p $(SHARE_DIR)/mime/packages
	cp $< $(SHARE_DIR)/mime/packages
	update-mime-database $(SHARE_DIR)/mime
	# Maybe better: xdg-mime install --mode user share/mime/packages/org.readmachine.ocrd-browser.xml


install-xdg-applications: share/applications/org.readmachine.ocrd-browser.desktop
	@mkdir -p $(SHARE_DIR)/applications
	@cp $< $(SHARE_DIR)/applications/org.readmachine.ocrd-browser.desktop
	@chmod +x $(SHARE_DIR)/applications/org.readmachine.ocrd-browser.desktop
	@update-desktop-database $(SHARE_DIR)/applications
	# Maybe better: xdg-desktop-menu install --mode user share/applications/org.readmachine.ocrd-browser.desktop
	$(info ### Done! You have to restart nautilus with)
	$(info ###     nautilus -q && nautilus &)
	$(info ### for the changes to have effect)

clean-build: pyclean
	rm -Rf build dist *.egg-info

pyclean:
	rm -f **/*.pyc
	rm -rf .pytest_cache
	rm -rf .mypy_cache/

build: clean-build
	$(PYTHON) -m build

testpypi: clean-build build
	twine upload --repository testpypi ./dist/browse[_-]ocrd*.{tar.gz,whl}

pypi: clean-build build
	twine upload ./dist/browse[_-]ocrd*.{tar.gz,whl}

flake8: deps-dev
	$(PYTHON) -m flake8 ocrd_browser tests

mypy: deps-dev
	$(PYTHON) -m mypy --show-error-codes  -p ocrd_browser

codespell: deps-dev
	codespell

test: tests/assets deps-dev
	$(PYTHON) -m xmlrunner discover -v -s tests --output-file $(CURDIR)/unittest.xml
	OCRD_METS_CACHING=true $(PYTHON) -m xmlrunner discover -v -s tests --output-file $(CURDIR)/unittest.xml

ci: flake8 mypy test codespell

# Clone OCR-D/assets to ./repo/assets
repo/assets:
	mkdir -p $(dir $@)
	git clone https://github.com/OCR-D/assets "$@"

# Setup test assets
tests/assets: repo/assets
	mkdir -p $@
	cp -r -t $@ repo/assets/data/*

docker-build: ocrd_browser/ui.gresource
	docker build --tag $(DOCKER_TAG) .

docker-run: DATADIR ?= $(CURDIR)
docker-run:
	docker run -it --rm -v $(DATADIR):/data -p 8085:8085 -p 8080:8080 $(DOCKER_TAG)

docker-up:
	docker-compose up -d

.PHONY: assets-clean
# Remove symlinks in test/assets
assets-clean:
	rm -rf test/assets
