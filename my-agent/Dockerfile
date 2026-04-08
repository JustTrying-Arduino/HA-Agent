ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip bash jq curl

COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY agent/ /opt/agent/
COPY workspace/ /usr/local/share/workspace/
COPY run.sh /
RUN chmod +x /run.sh

CMD ["/run.sh"]
