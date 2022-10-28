###
# Install everything we need
###
FROM python:3.12.0a1-alpine as install
LABEL maintainer="jeremy.frasier@trio.dhs.gov"
LABEL organization="CISA Cyber Assessments"
LABEL url="https://github.com/cisagov/saver"

ENV HOME=/home/saver
ENV USER=saver

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
    bash \
    openssl \
    redis \
    wget
RUN apk --no-cache --quiet upgrade
RUN apk --no-cache --quiet add $DEPS

###
# Make sure pip and setuptools are the latest versions
#
# Note that we use pip --no-cache-dir to avoid writing to a local
# cache.  This results in a smaller final image, at the cost of
# slightly longer install times.
###
RUN pip install --no-cache-dir --upgrade pip setuptools

###
# Install dependencies
###
RUN pip install --no-cache-dir --upgrade \
    https://github.com/cisagov/mongo-db-from-config/tarball/develop \
    pytz


###
# Setup the saver user and its home directory
###
FROM install AS setup_user

###
# Dependencies
#
# Install shadow, so we have adduser and addgroup.
#
# Setup user dependencies are only needed for setting up the user and
# will be removed at the end of that process.
###
ENV SETUP_USER_DEPS \
    shadow
RUN apk --no-cache --quiet add $SETUP_USER_DEPS

###
# Create unprivileged user
###
RUN addgroup -S $USER
RUN adduser -S -g "$USER user" -G $USER $USER

###
# Remove build dependencies
###
RUN apk --no-cache --quiet del $SETUP_USER_DEPS

# Put this just before we change users because the copy (and every
# step after it) will always be rerun by docker, but we need to be
# root for the chown command.
COPY . $HOME
RUN chown -R ${USER}:${USER} $HOME


###
# Setup working directory and entrypoint
###
FROM setup_user AS final

###
# Prepare to Run
###
# Right now we need to be root to create the file that
# tells the report container to grab the data from the database.
# USER saver:saver
WORKDIR $HOME
ENTRYPOINT ["./save_to_db.sh"]
