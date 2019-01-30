#!/usr/bin/env python3
import csv
import datetime
import yaml

from pymongo import MongoClient

DB_CONFIG_FILE = '/run/secrets/scan_write_creds.yml'
INCLUDE_DATA_DIR = '/home/saver/include/'
SHARED_DATA_DIR = '/home/saver/shared/'

AGENCIES_FILE = INCLUDE_DATA_DIR + 'agencies.csv'
CURRENT_FEDERAL_FILE = SHARED_DATA_DIR + 'artifacts/current-federal_modified.csv'


def db_from_config(config_filename):
    with open(config_filename, 'r') as stream:
        config = yaml.load(stream)

    try:
        db_uri = config['database']['uri']
        db_name = config['database']['name']
    except:
        print(f'Incorrect database config file format: {config_filename}')

    db_connection = MongoClient(host=db_uri, tz_aware=True)
    db = db_connection[db_name]
    return db


def main():
    # Import the agency mapping data
    with open(AGENCIES_FILE, 'r', newline='') as agencies_file:
        csvreader = csv.reader(agencies_file)
        agency_mapping = {row[0]: row[1] for row in csvreader}

    # Set up the scan database connection
    db = db_from_config(DB_CONFIG_FILE)

    # Import the current-federal data and create the records to be
    # inserted into the database.
    #
    # I hate using update_one() in a loop like this.  Once we move to
    # Mongo 4 we can use a transaction to atomically (1) drop all the
    # rows from the collection and (2) use insert_many() to insert all
    # the new data.  That will be much cleaner!
    now = datetime.datetime.utcnow()
    with open(CURRENT_FEDERAL_FILE, 'r', newline='') as current_federal_file:
        csvreader = csv.DictReader(current_federal_file)
        for row in csvreader:
            domain = row['Domain Name'].lower()
            agency = row['Agency'].replace('&', 'and')
            agency = agency.replace('/', ' ')
            agency = agency.replace('U. S.', 'U.S.')
            agency = agency.replace(',', '')

            cyhy_id = agency
            is_cyhy_stakeholder = False
            if agency in agency_mapping:
                # The agency is in the agency mapping file, so it is
                # mapped to a CyHy stakeholder
                cyhy_id = agency_mapping[agency]
                is_cyhy_stakeholder = True

            record = {
                'domain': domain,
                'agency': {
                    'id': cyhy_id,
                    'name': agency
                },
                'cyhy_stakeholder': is_cyhy_stakeholder,
                'scan_date': now
            }

            # Add this result to the database via an upsert
            res = db.domains.update_one({
                'domain': domain
            }, {
                '$set': record
            }, upsert=True)

            if not res.acknowledged:
                print(f'Unable to write new SLD record for {domain} to '
                      f'"{db.name}" database on {db.client.address[0]}.')

    # Now delete any entries whose scan_date is not now
    res = db.domains.delete_many({
        'scan_date': {
            '$ne': now
        }
    })
    if not res.acknowledged:
        print(f'Unable to delete old SLD records in "{db.name}" database '
              f'on {db.client.address[0]}.')
    else:
        print(f'Deleted {res.deleted_count} old SLD records from '
              f'"{db.name}" database on {db.client.address[0]}.')


if __name__ == '__main__':
    main()
