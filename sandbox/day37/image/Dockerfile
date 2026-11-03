# The build script resolves this official tag to an immutable repository digest.
ARG PYTHON_BASE
FROM ${PYTHON_BASE}

ARG PYTHON_BASE
LABEL org.abacus.day37="fixed-purpose-sandbox-probes"
LABEL org.abacus.base-image="${PYTHON_BASE}"
LABEL org.abacus.executor="python-json-v2"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --chown=0:0 probe.py executor.py worker.py /opt/abacus/

USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python", "/opt/abacus/probe.py"]
