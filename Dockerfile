FROM python:3.8

WORKDIR /
COPY Makefile .
COPY setup.cfg .
COPY setup.py .
COPY requirements.txt .
COPY README.md .
COPY ocrd_browser ocrd_browser
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-dev make \
    && make deps-ubuntu \
    && pip3 install -U setuptools pip \
    && pip3 install -e / \
    && rm Makefile

MAINTAINER https://github.com/hnesk/browse-ocrd/issues

ENV GDK_BACKEND broadway
ENV BROADWAY_DISPLAY :5

EXPOSE 8085
EXPOSE 8080

VOLUME /data

COPY init.sh .
COPY serve.py .

CMD ["/init.sh", "/data"]
