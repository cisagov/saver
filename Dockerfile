FROM python:3.11.1-alpine

###
# For a list of pre-defined annotation keys and value types see:
# https://github.com/opencontainers/image-spec/blob/master/annotations.md
#
# Note: Additional labels are added by the build workflow.
###
LABEL org.opencontainers.image.authors="vm-fusion-dev-group@trio.dhs.gov"
LABEL org.opencontainers.image.vendor="Cybersecurity and Infrastructure Security Agency"

###
# Unprivileged user setup variables
###
# TODO: Change this to 2048.  See cisagov/orchestrator#130 for more
# details.
ARG CISA_UID=421
ARG CISA_GID=${CISA_UID}
ARG CISA_USER="cisa"
ENV CISA_GROUP=${CISA_USER}
ENV CISA_HOME="/home/${CISA_USER}"

###
# Upgrade the system
#
# Note that we use apk --no-cache to avoid writing to a local cache.
# This results in a smaller final image, at the cost of slightly
# longer install times.
###
RUN apk --update --no-cache --quiet upgrade

###
# Create unprivileged user
###
RUN addgroup --system --gid ${CISA_UID} ${CISA_GROUP} \
    && adduser --system --uid ${CISA_UID} --ingroup ${CISA_GROUP} ${CISA_USER}

###
# Dependencies
#
# We need redis so we can use redis-cli to communicate with redis.  I
# also reinstall wget with openssl, since otherwise wget does not seem
# to know how to HTTPS.
#
# Note that we use apk --no-cache to avoid writing to a local cache.
# This results in a smaller final image, at the cost of slightly
# longer install times.
###
ENV DEPS \
    openssl \
    redis \
    wget
RUN apk --no-cache --quiet add ${DEPS}

###
# Make sure pip, setuptools, and wheel are the latest versions
#
# Note that we use pip3 --no-cache-dir to avoid writing to a local
# cache.  This results in a smaller final image, at the cost of
# slightly longer install times.
###
RUN pip3 install --no-cache-dir --upgrade \
    pip \
    setuptools \
    wheel

###
# Install Python dependencies
###
RUN pip3 install --no-cache-dir --upgrade \
    https://github.com/cisagov/mongo-db-from-config/tarball/develop \
    pytz

###
# Put this just before we change users because the copy (and every
# step after it) will always be rerun by Docker, but we need to be
# root for the chown command.
###
COPY src/*.py src/*.sh ${CISA_HOME}
COPY src/include ${CISA_HOME}/include
RUN chown -R ${CISA_USER}:${CISA_GROUP} ${CISA_HOME}

###
# Prepare to run
###
# TODO: Right now we need to be root at runtime in order to create
# files in ${CISA_HOME}/shared, but see cisagov/orchestrator#130.
# USER ${CISA_USER}:${CISA_GROUP}
WORKDIR ${CISA_HOME}
ENTRYPOINT ["./save_to_db.sh"]
