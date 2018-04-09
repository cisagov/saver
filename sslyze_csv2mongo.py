#!/usr/bin/env python3
import csv
import re
import yaml
import sys
import datetime
from pymongo import MongoClient
from pytz import timezone

DB_CONFIG_FILE = '/run/secrets/scan_write_creds.yml'
INCLUDE_DATA_DIR = '/home/saver/include/'
SHARED_DATA_DIR = '/home/saver/shared/'

AGENCIES_FILE = INCLUDE_DATA_DIR + 'agencies.csv'

CURRENT_FEDERAL_FILE = SHARED_DATA_DIR + 'artifacts/current-federal_modified.csv'
UNIQUE_AGENCIES_FILE = SHARED_DATA_DIR + 'artifacts/unique-agencies.csv'
CLEAN_CURRENT_FEDERAL_FILE = SHARED_DATA_DIR + 'artifacts/clean-current-federal.csv'

SSLYZE_RESULTS_FILE = SHARED_DATA_DIR + 'artifacts/results/sslyze.csv'


# Take a sorted csv from a domain scan and populate a mongo database with the results
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
    for row in csv.reader(current_federal):
        if row[0] == 'Domain Name':
            continue
        domain = row[0]
        agency = row[2].replace('&', 'and').replace('/', ' ').replace('U. S.', 'U.S.').replace(',', '')

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
    date_today = datetime.datetime.combine(datetime.datetime.utcnow(), datetime.time.min)
    db = db_from_config(db_config_file)   # set up database connection
    f = open(SSLYZE_RESULTS_FILE)
    csv_f = csv.reader(f)
    domain_list = []

    for row in clean_federal:
        da = Domainagency(row[0].lower(), row[1])
        domain_list.append(da)

    # Reset previous "latest:True" flags to False
    db.sslyze_scan.update({'latest':True}, {'$set':{'latest':False}}, multi=True)

    print('Importing to "{}" database on {}...'.format(db.name, db.client.address[0]))
    domains_processed = 0
    for row in sorted(csv_f):
        # Skip header row if present
        if row[0] == 'Domain':
            continue

        # Because of the way domain-scan works, if a domain does not need to be
        # scanned because pshtt and trustymail have determined that there are
        # no web or mail servers, then a row of null data is output.  We should
        # skip such rows.  Such rows have a null for the "scanned port" field.
        if not row[3]:
            continue

        # Fix up the integer entries
        #
        # row[3] = scanned port, row[13] = weakest_dh_group_size, row[18] =
        # key_length
        for index in (3, 13, 18):
            if row[index]:
                row[index] = int(row[index])
            else:
                row[index] = -1  # -1 means null

        # Match base_domain
        for domain in domain_list:
            if domain.domain == row[1]:
                agency = domain.agency
                break
            else:
                agency = ''

        if agency in agency_dict:
            id = agency_dict[agency]
        else:
            id = agency

        # Convert 'True'/'False' strings to boolean values (or None)
        for boolean_item in (4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 20, 21, 27):
            if row[boolean_item] == 'True':
                row[boolean_item] = True
            elif row[boolean_item] == 'False':
                row[boolean_item] = False
            else:
                row[boolean_item] = None

        # Convert date/time strings to Python datetime
        #
        # Note that the date/time strings returned by sslyze are UTC:
        # https://github.com/pyca/cryptography/blob/master/src/cryptography/x509/base.py#L481-L526
        # They are also in the format YYYY-MM-DDTHH:MM:SS.
        for index in (21, 22):
            if row[index]:
                row[index] = datetime.datetime.strptime(row[index], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone('US/Eastern'))
            else:
                row[index] = None

        db.sslyze_scan.insert_one({
            'domain': row[0],
            'base_domain': row[1],
            'is_base_domain': row[0] == row[1],
            'agency': {'id':id, 'name':agency},
            'scanned_hostname': row[2],
            'scanned_port': row[3],
            'starttls_smtp': row[4],
            'sslv2': row[5],
            'sslv3': row[6],
            'tlsv1_0': row[7],
            'tlsv1_1': row[8],
            'tlsv1_2': row[9],
            'tlsv1_3': row[10],
            'any_forward_secrecy': row[11],
            'all_forward_secrecy': row[12],
            'weakest_dh_group_size': row[13],
            'any_rc4': row[14],
            'all_rc4': row[15],
            'any_3des': row[16],
            'key_type': row[17],
            'key_length': row[18],
            'signature_algorithm': row[19],
            'sha1_in_served_chain': row[20],
            'sha1_in_construsted_chain': row[21],
            'not_before': row[22],
            'not_after': row[23],
            'highest_served_issuer': row[24],
            'highest_constructed_issuer': row[25],
            'errors': row[26],
            'is_symantec_cert': row[27],
            'symantec_distrust_date': row[28],
            'scan_date': date_today,
            'latest': True
        })
        domains_processed += 1

    print('Successfully imported {} documents to "{}" database on {}'.format(domains_processed, db.name, db.client.address[0]))

if __name__ == "__main__":
    main()
