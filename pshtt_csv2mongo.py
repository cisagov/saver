#!/usr/bin/env python3
import csv
import re
import yaml
import sys
import datetime
from pymongo import MongoClient

DB_CONFIG_FILE = '/run/secrets/pshtt_write_creds.yml'
INCLUDE_DATA_DIR = '/home/saver/include/'
SHARED_DATA_DIR = '/home/saver/shared/'

REWRITES_FILE = INCLUDE_DATA_DIR + 'rewrites.csv'
NON_CYHY_STAKEHOLDERS_FILE = INCLUDE_DATA_DIR + 'noncyhy.csv'
AGENCIES_FILE = INCLUDE_DATA_DIR + 'agencies.csv'

CURRENT_FEDERAL_FILE = SHARED_DATA_DIR + 'artifacts/current-federal-original.csv'
UNIQUE_AGENCIES_FILE = SHARED_DATA_DIR + 'artifacts/unique-agencies.csv'
CLEAN_CURRENT_FEDERAL_FILE = SHARED_DATA_DIR + 'artifacts/clean-current-federal.csv'

PSHTT_RESULTS_FILE = SHARED_DATA_DIR + 'artifacts/results/pshtt.csv'


# Take a sorted csv from a domain scan and populate a mongo database with the results
class Domainagency():
    def __init__(self, domain, agency):
        self.domain = domain
        self.agency = agency


def main():
    opened_files = open_csv_files()
    store_data(opened_files[0], opened_files[1],
               opened_files[2], DB_CONFIG_FILE)


def open_csv_files():
    rewrites = open(REWRITES_FILE)
    current_federal = open(CURRENT_FEDERAL_FILE)
    agencies = open(AGENCIES_FILE)
    unique_agencies = open(UNIQUE_AGENCIES_FILE, "w+")
    non_stakeholders = open(NON_CYHY_STAKEHOLDERS_FILE)

    # Create a writer so we have a list of our unique agencies
    writer = csv.writer(unique_agencies, delimiter=",")

    # Create a dictionary for rewrites.
    rewrite_dict = {}
    for row in csv.reader(rewrites):
        rewrite_dict[row[0]] = row[1]

    noncyhy = {}
    for row in csv.reader(non_stakeholders):
        noncyhy[row[0]] = row[1]

    # Get the cleaned current-federal
    clean_federal = []
    unique = set()
    for row in csv.reader(current_federal):
        if row[0] == "Domain Name":
            continue
        domain = row[0]
        agency = row[2].replace("&", "and").replace("/", " ").replace("U. S.", "U.S.").replace(",", "")

        for key in rewrite_dict:
            agency = agency.replace(key.strip(), rewrite_dict[key])

        # Noncyhy dict contains some rewrites for non cyhy agencies.
        if agency in noncyhy:
            agency = noncyhy[agency]

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
    clean_output = open(CLEAN_CURRENT_FEDERAL_FILE, "w+")
    writer = csv.writer(clean_output)
    for line in clean_federal:
        writer.writerow(line)

    return clean_federal, agency_dict, noncyhy.values()

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


def store_data(clean_federal, agency_dict, noncyhy, db_config_file):
    date_today = datetime.datetime.combine(datetime.datetime.utcnow(), datetime.time.min)
    db = db_from_config(db_config_file)   # set up database connection
    f = open(PSHTT_RESULTS_FILE)
    csv_f = csv.reader(f)
    domain_list = []

    for row in clean_federal:
        da = Domainagency(row[0].lower(), row[1])
        domain_list.append(da)

    # Reset previous "latest:True" flags to False
    db.https_scan.update({'latest':True}, {'$set':{'latest':False}}, multi=True)

    print('Importing to "{}" database on {}...'.format(db.name, db.client.address[0]))
    domains_processed = 0
    for row in sorted(csv_f):
        # Skip header row if present
        if row[0] == "Domain":
            continue

        if row[16]:  # row[16] = hsts_max_age.
            row[16] = int(row[16])
        else:
            row[16] = -1  # -1 means null

        # Match base_domain
        for domain in domain_list:
            if domain.domain == row[1]:
                agency = domain.agency
                break
            else:
                agency = ""

        if agency in agency_dict:
            id = agency_dict[agency]
        else:
            id = agency

        # Convert "True"/"False" strings to boolean values (or None)
        for boolean_item in (3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21, 22, 23, 24, 25):
            if row[boolean_item] == 'True':
                row[boolean_item] = True
            elif row[boolean_item] == 'False':
                row[boolean_item] = False
            else:
                row[boolean_item] = None

        db.https_scan.insert_one(
            {"domain": row[0],
            "base_domain": row[1],
            "agency": agency,
            "agency_id": id,
            "canonical_url": row[2],
            "live": row[3],
            "redirect": row[4],
            "redirect_to": row[5],
            "valid_https": row[6],
            "defaults_https": row[7],
            "downgrades_https": row[8],
            "strictly_forces_https": row[9],
            "https_bad_chain": row[10],
            "https_bad_hostname": row[11],
            "https_expired_cert": row[12],
            "https_self_signed_cert": row[13],
            "hsts": row[14],
            "hsts_header": re.sub(';', '', row[15]),
            "hsts_max_age": row[16],
            "hsts_entire_domain": row[17],
            "hsts_preload_ready": row[18],
            "hsts_preload_pending": row[19],
            "hsts_preloaded": row[20],
            "hsts_base_domain_preloaded": row[21],
            "domain_supports_https": row[22],
            "domain_enforces_https": row[23],
            "domain_uses_strong_hsts": row[24],
            "unknown_error": row[25],
            "cyhy_stakeholder": agency not in noncyhy,
            "scan_date": date_today,
            "latest": True})
        domains_processed += 1

    print('Successfully imported {} documents to "{}" database on {}'.format(domains_processed, db.name, db.client.address[0]))

if __name__ == "__main__":
    main()
