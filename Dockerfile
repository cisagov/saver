FROM python:3.6.4-alpine3.7
MAINTAINER Shane Frasier <jeremy.frasier@beta.dhs.gov>
###
# Install shadow, so we have adduser and addgroup.  We can remove the
# package once we're finished with it.
#
# We need redis so we can use redis-cli to communicate with redis.  I
# also reinstall wget with openssl, since otherwise wget does not seem
# to know how to HTTPS.
###
RUN apk --no-cache add wget openssl redis shadow

# Upgrade pip and setuptools
RUN pip3 install --upgrade pip setuptools

###
# Dependencies
###
RUN pip3 install --upgrade pymongo pytz pyyaml

###
# Create unprivileged user
###
ENV SAVER_HOME=/home/saver
RUN addgroup -S saver \
    && adduser -S -g "Saver user" -G saver saver

# Remove build dependencies
RUN apk --no-cache del shadow

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
