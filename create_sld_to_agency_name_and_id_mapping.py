#!/usr/bin/env python3
import csv
import datetime
import yaml

from pymongo import MongoClient

SCAN_DB_CONFIG_FILE = '/run/secrets/scan_write_creds.yml'
CYHY_DB_CONFIG_FILE = '/run/secrets/cyhy_read_creds.yml'
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

    # Set up the cyhy database connection
    cyhy_db = db_from_config(CYHY_DB_CONFIG_FILE)

    # Import the current-federal data and create the records to be
    # inserted into the database
    now = datetime.datetime.utcnow()
    records = []
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
            else:
                # There are cases where an agency is not in the agency
                # mapping file because its name as listed in
                # current-federal is identical to its CyHy ID.  (See
                # AMTRAK, for instance.)  In that case
                # is_cyhy_stakeholder needs to be set to true.
                if cyhy_db.requests.count_documents({'_id': agency}) != 0:
                    is_cyhy_stakeholder = True

            records.append({
                'domain': domain,
                'agency': {
                    'id': cyhy_id,
                    'name': agency
                },
                'cyhy_stakeholder': is_cyhy_stakeholder,
                'scan_date': now
            })

    # Set up the scan database connection
    scan_db = db_from_config(SCAN_DB_CONFIG_FILE)

    # Drop all previous documents from domains collection
    #
    # It would be great to check the return code here, but I don't see
    # anything of use in DeleteResult:
    # http://api.mongodb.com/python/current/api/pymongo/results.html#pymongo.results.DeleteResult
    scan_db.domains.delete_many({})

    # Now add our new results
    res = scan_db.domains.insert_many(records)
    if len(res.inserted_ids) != len(records):
        print(f'Unable to write new SLD records from "{scan_db.name}" '
              f'database on {scan_db.client.address[0]}')
        return

    print(f'Successfully imported {len(records)} SLDs to "{scan_db.name}" '
          f'database on {scan_db.client.address[0]}')


if __name__ == '__main__':
    main()
