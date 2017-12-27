FROM python:3.6.3-alpine3.6
MAINTAINER Shane Frasier <jeremy.frasier@beta.dhs.gov>
###
# Install shadow, so we have adduser and addgroup.  We can remove the
# package once we're finished with it.
#
# We also need redis so we can use redis-cli to communicate with
# redis.
###
RUN apk update && \
    apk add redis shadow

###
# Dependencies
###
RUN pip3 install pymongo pytz pyyaml

###
# Create unprivileged user
###
ENV SAVER_HOME=/home/saver
RUN addgroup -S saver \
    && adduser -S -g "Saver user" -G saver saver

# Remove build dependencies
RUN apk del shadow

# Put this just before we change users because the copy (and every
# step after it) will always be rerun by docker, but we need to be
# root for the chown command.
COPY . $SAVER_HOME
RUN chown -R saver:saver ${SAVER_HOME}

###
# Prepare to Run
###
# Right now we need to be root to create the file that
# tells the report container to grab the data from the database.
# USER saver:saver
WORKDIR $SAVER_HOME
ENTRYPOINT ["./save_to_db.sh"]
