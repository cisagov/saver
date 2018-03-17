#!/bin/sh

SHARED_DIR='/home/saver/shared'

echo 'Waiting for scanner'
while [ "$(redis-cli -h orchestrator_redis_1 get scanning_complete)" != "true" ]
do
    sleep 5
done
echo "Scanner finished"

# No longer needed
redis-cli -h orchestrator_redis_1 del scanning_complete

# Process scan results and import them to the database
echo 'Processing results...'
./pshtt_csv2mongo.py
rm $SHARED_DIR/artifacts/unique-agencies.csv
rm $SHARED_DIR/artifacts/clean-current-federal.csv
./trustymail_csv2mongo.py
rm $SHARED_DIR/artifacts/unique-agencies.csv
rm $SHARED_DIR/artifacts/clean-current-federal.csv
./sslyze_csv2mongo.py
# Leave a copy of unique-agencies.csv and clean-current-federal.csv
# since the report tool will need it

# Let redis know we're done
redis-cli -h orchestrator_redis_1 set saving_complete true
