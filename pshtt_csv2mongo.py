#!/usr/bin/env python3
import csv
import re
import yaml
import datetime
from pymongo import MongoClient

DB_CONFIG_FILE = '/run/secrets/scan_write_creds.yml'
INCLUDE_DATA_DIR = '/home/saver/include/'
SHARED_DATA_DIR = '/home/saver/shared/'

AGENCIES_FILE = INCLUDE_DATA_DIR + 'agencies.csv'

CURRENT_FEDERAL_FILE = SHARED_DATA_DIR + \
    'artifacts/current-federal_modified.csv'
UNIQUE_AGENCIES_FILE = SHARED_DATA_DIR + \
    'artifacts/unique-agencies.csv'
CLEAN_CURRENT_FEDERAL_FILE = SHARED_DATA_DIR + \
    'artifacts/clean-current-federal.csv'

PSHTT_RESULTS_FILE = SHARED_DATA_DIR + 'artifacts/results/pshtt.csv'


# Take a sorted csv from a domain scan and populate a mongo database
# with the results
class Domainagency():
    def __init__(self, domain, agency):
        self.domain = domain
        self.agency = agency


def main():
    opened_files = open_csv_files()
    store_data(opened_files[0], opened_files[1], DB_CONFIG_FILE)


def open_csv_files():
    current_federal = open(CURRENT_FEDERAL_FILE)
    agencies = open(AGENCIES_FILE)
    unique_agencies = open(UNIQUE_AGENCIES_FILE, 'w+')

    # Create a writer so we have a list of our unique agencies
    writer = csv.writer(unique_agencies, delimiter=',')

    # Get the cleaned current-federal
    clean_federal = []
    unique = set()
    for row in csv.DictReader(current_federal):
        domain = row['Domain Name']
        agency = row['Agency'].replace(
            '&', 'and'
        ).replace(
            '/', ' '
        ).replace(
            'U. S.', 'U.S.'
        ).replace(
            ',', ''
        )

        # Store the unique agencies that we see
        unique.add(agency)

        clean_federal.append([domain, agency])

    # Prepare the agency list agency_name : agency_id
    agency_dict = {}
    for row in csv.reader(agencies):
        agency_dict[row[0]] = row[1]

    # Write out the unique agencies
    for agency in unique:
        writer.writerow([agency])

    # Create the clean-current-federal for use later.
    # TODO: Remove this and have it handled in code.
    clean_output = open(CLEAN_CURRENT_FEDERAL_FILE, 'w+')
    writer = csv.writer(clean_output)
    for line in clean_federal:
        writer.writerow(line)

    return clean_federal, agency_dict


def db_from_config(config_filename):
    with open(config_filename, 'r') as stream:
        config = yaml.load(stream)

    try:
        db_uri = config['database']['uri']
        db_name = config['database']['name']
    except:
        print('Incorrect database config file format: {}'.format(config_filename))

    db_connection = MongoClient(host=db_uri, tz_aware=True)
    db = db_connection[db_name]
    return db


def store_data(clean_federal, agency_dict, db_config_file):
    date_today = datetime.datetime.combine(datetime.datetime.utcnow(),
                                           datetime.time.min)
    db = db_from_config(db_config_file)   # set up database connection
    f = open(PSHTT_RESULTS_FILE)
    csv_f = csv.DictReader(f)
    domain_list = []

    for row in clean_federal:
        da = Domainagency(row[0].lower(), row[1])
        domain_list.append(da)

    # Reset previous "latest:True" flags to False
    db.https_scan.update(
        {
            'latest': True
        },
        {
            '$set': {
                'latest': False
            }
        }, multi=True)

    print('Importing to "{}" database on {}...'.format(db.name,
                                                       db.client.address[0]))
    domains_processed = 0
    for row in sorted(csv_f, key=lambda r: r['Domain']):
        # Fix up the integer entries
        integer_items = (
            'HSTS Max Age',
        )
        for integer_item in integer_items:
            if row[integer_item]:
                row[integer_item] = int(row[integer_item])
            else:
                row[integer_item] = -1  # -1 means null

        # Match base_domain
        for domain in domain_list:
            if domain.domain == row['Base Domain']:
                agency = domain.agency
                break
            else:
                agency = ''

        if agency in agency_dict:
            id = agency_dict[agency]
        else:
            id = agency

        # Convert "True"/"False" strings to boolean values (or None)
        boolean_items = (
            'Live',
            'Redirect',
            'Valid HTTPS',
            'Defaults to HTTPS',
            'Downgrades HTTPS',
            'Strictly Forces HTTPS',
            'HTTPS Bad Chain',
            'HTTPS Bad Hostname',
            'HTTPS Expired Cert',
            'HTTPS Self Signed Cert',
            'HSTS',
            'HSTS Entire Domain',
            'HSTS Preload Ready',
            'HSTS Preload Pending',
            'HSTS Preloaded',
            'Base Domain HSTS Preloaded',
            'Domain Supports HTTPS',
            'Domain Enforces HTTPS',
            'Domain Uses Strong HSTS',
            'Unknown Error'
        )
        for boolean_item in boolean_items:
            if row[boolean_item] == 'True':
                row[boolean_item] = True
            elif row[boolean_item] == 'False':
                row[boolean_item] = False
            else:
                row[boolean_item] = None

        db.https_scan.insert_one({
            'domain': row['Domain'],
            'base_domain': row['Base Domain'],
            'is_base_domain': row['Domain'] == row['Base Domain'],
            'agency': {
                'id': id,
                'name': agency
            },
            'canonical_url': row['Canonical URL'],
            'live': row['Live'],
            'redirect': row['Redirect'],
            'redirect_to': row['Redirect To'],
            'valid_https': row['Valid HTTPS'],
            'defaults_https': row['Defaults to HTTPS'],
            'downgrades_https': row['Downgrades HTTPS'],
            'strictly_forces_https': row['Strictly Forces HTTPS'],
            'https_bad_chain': row['HTTPS Bad Chain'],
            'https_bad_hostname': row['HTTPS Bad Hostname'],
            'https_expired_cert': row['HTTPS Expired Cert'],
            'https_self_signed_cert': row['HTTPS Self Signed Cert'],
            'hsts': row['HSTS'],
            'hsts_header': re.sub(';', '', row['HSTS Header']),
            'hsts_max_age': row['HSTS Max Age'],
            'hsts_entire_domain': row['HSTS Entire Domain'],
            'hsts_preload_ready': row['HSTS Preload Ready'],
            'hsts_preload_pending': row['HSTS Preload Pending'],
            'hsts_preloaded': row['HSTS Preloaded'],
            'hsts_base_domain_preloaded': row['Base Domain HSTS Preloaded'],
            'domain_supports_https': row['Domain Supports HTTPS'],
            'domain_enforces_https': row['Domain Enforces HTTPS'],
            'domain_uses_strong_hsts': row['Domain Uses Strong HSTS'],
            'unknown_error': row['Unknown Error'],
            'scan_date': date_today,
            'latest': True
        })
        domains_processed += 1

    print('Successfully imported {} documents to "{}" database on {}'.format(domains_processed,
                                                                             db.name,
                                                                             db.client.address[0]))


if __name__ == '__main__':
    main()
