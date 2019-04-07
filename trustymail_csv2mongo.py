#!/usr/local/bin/python3

import csv
import datetime

from mongo_db_from_config import db_from_config

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

TRUSTYMAIL_RESULTS_FILE = SHARED_DATA_DIR + 'artifacts/results/trustymail.csv'


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
    agencies = open(AGENCIES_FILE)
    current_federal = open(CURRENT_FEDERAL_FILE)

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


def store_data(clean_federal, agency_dict, db_config_file):
    date_today = datetime.datetime.combine(datetime.datetime.utcnow(),
                                           datetime.time.min)
    db = db_from_config(db_config_file)   # set up database connection
    f = open(TRUSTYMAIL_RESULTS_FILE)
    csv_f = csv.DictReader(f)
    domain_list = []

    for row in clean_federal:
        da = Domainagency(row[0].lower(), row[1])
        domain_list.append(da)

    # Reset previous "latest:True" flags to False
    db.trustymail.update(
        {
            'latest': True
        },
        {
            '$set': {
                'latest': False
            }
        },
        multi=True
    )

    print('Importing to "{}" database on {}...'.format(db.name,
                                                       db.client.address[0]))
    domains_processed = 0
    for row in sorted(csv_f, key=lambda r: r['Domain']):
        # Fix up the integer entries
        integer_items = (
            'DMARC Policy Percentage',
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
            'MX Record',
            'Domain Supports SMTP',
            'Domain Supports STARTTLS',
            'SPF Record',
            'Valid SPF',
            'DMARC Record',
            'Valid DMARC',
            'DMARC Record on Base Domain',
            'Valid DMARC Record on Base Domain',
            'DMARC Has Aggregate Report URI',
            'DMARC Has Forensic Report URI'
        )
        for boolean_item in boolean_items:
            if row[boolean_item] == 'True':
                row[boolean_item] = True
            elif row[boolean_item] == 'False':
                row[boolean_item] = False
            else:
                row[boolean_item] = None

        # Split the rua and ruf addresses into arrays of dictionaries
        def split_rua_or_ruf(text):
            """Split an rua or ruf into the URI and modifier, if any.

            See section 6.2 of the RFC for details on the format
            (https://tools.ietf.org/html/rfc7489).

            Parameters
            ----------
            text : str
                The rua or ruf string to be split into its constituent
                parts.

            Returns
            -------
            dict: The rua or ruf aplit into its URI and modifier, if
            any.
            """
            pieces = text.split('!')
            uri = pieces[0]
            modifier = None
            if len(pieces) > 1:
                modifier = pieces[1]
            return {'uri': uri, 'modifier': modifier}

        # The if clauses at the end drop empty strings
        ruas = [
            split_rua_or_ruf(rua.strip())
            for rua in row['DMARC Aggregate Report URIs'].split(',')
            if rua
        ]
        rufs = [
            split_rua_or_ruf(ruf.strip())
            for ruf in row['DMARC Forensic Report URIs'].split(',')
            if ruf
        ]

        db.trustymail.insert_one({
            'domain': row['Domain'],
            'base_domain': row['Base Domain'],
            'is_base_domain': row['Domain'] == row['Base Domain'],
            'agency': {
                'id': id,
                'name': agency
            },
            'live': row['Live'],
            'mx_record': row['MX Record'],
            'mail_servers': row['Mail Servers'],
            'mail_server_ports_tested': row['Mail Server Ports Tested'],
            'domain_supports_smtp': row['Domain Supports SMTP'],
            'domain_supports_smtp_results': row[
                'Domain Supports SMTP Results'
            ],
            'domain_supports_starttls': row['Domain Supports STARTTLS'],
            'domain_supports_starttls_results': row[
                'Domain Supports STARTTLS Results'
            ],
            'spf_record': row['SPF Record'],
            'valid_spf': row['Valid SPF'],
            'spf_results': row['SPF Results'],
            'dmarc_record': row['DMARC Record'],
            'valid_dmarc': row['Valid DMARC'],
            'dmarc_results': row['DMARC Results'],
            'dmarc_record_base_domain': row['DMARC Record on Base Domain'],
            'valid_dmarc_base_domain': row[
                'Valid DMARC Record on Base Domain'
            ],
            'dmarc_results_base_domain': row['DMARC Results on Base Domain'],
            'dmarc_policy': row['DMARC Policy'],
            'dmarc_subdomain_policy': row['DMARC Subdomain Policy'],
            'dmarc_policy_percentage': row['DMARC Policy Percentage'],
            'aggregate_report_uris': ruas,
            'forensic_report_uris': rufs,
            'has_aggregate_report_uri': row['DMARC Has Aggregate Report URI'],
            'has_forensic_report_uri': row['DMARC Has Forensic Report URI'],
            'syntax_errors': row['Syntax Errors'],
            'debug_info': row['Debug Info'],
            'scan_date': date_today,
            'latest': True
        })
        domains_processed += 1

    print('Successfully imported {} documents to "{}" database on '
          '{}'.format(domains_processed, db.name, db.client.address[0]))
    # import IPython; IPython.embed() #<<< BREAKPOINT >>>


if __name__ == '__main__':
    main()
