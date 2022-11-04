#!/usr/bin/env python3

"""Populate MongoDB from a sorted CSV file as output by domain scan."""

# Standard Python Libraries
import csv
import datetime

# Third-Party Libraries
from mongo_db_from_config import db_from_config
from pytz import timezone

DB_CONFIG_FILE = "/run/secrets/scan_write_creds.yml"
INCLUDE_DATA_DIR = "/home/saver/include/"
SHARED_DATA_DIR = "/home/saver/shared/"

AGENCIES_FILE = INCLUDE_DATA_DIR + "agencies.csv"

CURRENT_FEDERAL_FILE = SHARED_DATA_DIR + "artifacts/current-federal_modified.csv"
UNIQUE_AGENCIES_FILE = SHARED_DATA_DIR + "artifacts/unique-agencies.csv"
CLEAN_CURRENT_FEDERAL_FILE = SHARED_DATA_DIR + "artifacts/clean-current-federal.csv"

SSLYZE_RESULTS_FILE = SHARED_DATA_DIR + "artifacts/results/sslyze.csv"


class Domainagency:
    """A data container for domain and agency."""

    def __init__(self, domain, agency):
        """Initialize the container.

        :param domain: The domain object
        :param agency: The agency object
        """
        self.domain = domain
        self.agency = agency


def main():
    """Save the sslyze data."""
    opened_files = open_csv_files()
    store_data(opened_files[0], opened_files[1], DB_CONFIG_FILE)


def open_csv_files():
    """Return information about federal agencies from CSV files.

    :return: A cleaned up version of current federal and a dict of
    agency IDs keyed by agency name
    """
    current_federal = open(CURRENT_FEDERAL_FILE)
    agencies = open(AGENCIES_FILE)
    unique_agencies = open(UNIQUE_AGENCIES_FILE, "w+")

    # Create a writer so we have a list of our unique agencies
    writer = csv.writer(unique_agencies, delimiter=",")

    # Get the cleaned current-federal
    clean_federal = []
    unique = set()
    for row in csv.DictReader(current_federal):
        domain = row["Domain Name"]
        agency = (
            row["Agency"]
            .replace("&", "and")
            .replace("/", " ")
            .replace("U. S.", "U.S.")
            .replace(",", "")
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
    clean_output = open(CLEAN_CURRENT_FEDERAL_FILE, "w+")
    writer = csv.writer(clean_output)
    for line in clean_federal:
        writer.writerow(line)

    return clean_federal, agency_dict


def store_data(clean_federal, agency_dict, db_config_file):
    """Save the sslyze data to the database.

    :param clean_federal: The cleaned up version of current federal
    returned by open_csv_files()
    :param agency_dict: The agency dictionary returned by
    open_csv_files()
    :param db_config_file: The name of the file where the database
    configuration is stored
    """
    date_today = datetime.datetime.combine(
        datetime.datetime.utcnow(), datetime.time.min
    )
    db = db_from_config(db_config_file)  # set up database connection
    f = open(SSLYZE_RESULTS_FILE)
    csv_f = csv.DictReader(f)
    domain_list = []

    for row in clean_federal:
        da = Domainagency(row[0].lower(), row[1])
        domain_list.append(da)

    # Reset previous "latest:True" flags to False
    db.sslyze_scan.update_many({"latest": True}, {"$set": {"latest": False}})

    print('Importing to "{}" database on {}...'.format(db.name, db.client.address[0]))
    domains_processed = 0
    for row in sorted(csv_f, key=lambda r: r["Domain"]):
        # Because of the way domain-scan works, if a domain does not need to be
        # scanned because pshtt and trustymail have determined that there are
        # no web or mail servers, then a row of null data is output.  We should
        # skip such rows.  Such rows have a null for the "scanned port" field.
        if not row["Scanned Port"]:
            continue

        # Fix up the integer entries
        integer_items = ("Scanned Port", "Key Length")
        for integer_item in integer_items:
            if row[integer_item]:
                row[integer_item] = int(row[integer_item])
            else:
                row[integer_item] = -1  # -1 means null

        # Match base_domain
        for domain in domain_list:
            if domain.domain == row["Base Domain"]:
                agency = domain.agency
                break
            else:
                agency = ""

        if agency in agency_dict:
            id = agency_dict[agency]
        else:
            id = agency

        # Convert 'True'/'False' strings to boolean values (or None)
        boolean_items = (
            "STARTTLS SMTP",
            "SSLv2",
            "SSLv3",
            "TLSv1.0",
            "TLSv1.1",
            "TLSv1.2",
            "TLSv1.3",
            "Any Forward Secrecy",
            "All Forward Secrecy",
            "Any RC4",
            "All RC4",
            "Any 3DES",
            "SHA-1 in Served Chain",
            "SHA-1 in Constructed Chain",
            "Is Symantec Cert",
        )
        for boolean_item in boolean_items:
            if row[boolean_item] == "True":
                row[boolean_item] = True
            elif row[boolean_item] == "False":
                row[boolean_item] = False
            else:
                row[boolean_item] = None

        # Convert date/time strings to Python datetime
        #
        # Note that the date/time strings returned by sslyze are UTC:
        # https://github.com/pyca/cryptography/blob/master/src/cryptography/x509/base.py#L481-L526
        # They are also in the format YYYY-MM-DDTHH:MM:SS.
        date_items = ("Not Before", "Not After")
        for date_item in date_items:
            if row[date_item]:
                row[date_item] = datetime.datetime.strptime(
                    row[date_item], "%Y-%m-%dT%H:%M:%S"
                ).replace(tzinfo=timezone("US/Eastern"))
            else:
                row[date_item] = None

        db.sslyze_scan.insert_one(
            {
                "domain": row["Domain"],
                "base_domain": row["Base Domain"],
                "is_base_domain": row["Domain"] == row["Base Domain"],
                "agency": {"id": id, "name": agency},
                "scanned_hostname": row["Scanned Hostname"],
                "scanned_port": row["Scanned Port"],
                "starttls_smtp": row["STARTTLS SMTP"],
                "sslv2": row["SSLv2"],
                "sslv3": row["SSLv3"],
                "tlsv1_0": row["TLSv1.0"],
                "tlsv1_1": row["TLSv1.1"],
                "tlsv1_2": row["TLSv1.2"],
                "tlsv1_3": row["TLSv1.3"],
                "any_forward_secrecy": row["Any Forward Secrecy"],
                "all_forward_secrecy": row["All Forward Secrecy"],
                "any_rc4": row["Any RC4"],
                "all_rc4": row["All RC4"],
                "any_3des": row["Any 3DES"],
                "key_type": row["Key Type"],
                "key_length": row["Key Length"],
                "signature_algorithm": row["Signature Algorithm"],
                "sha1_in_served_chain": row["SHA-1 in Served Chain"],
                "sha1_in_construsted_chain": row["SHA-1 in Constructed Chain"],
                "not_before": row["Not Before"],
                "not_after": row["Not After"],
                "highest_served_issuer": row["Highest Served Issuer"],
                "highest_constructed_issuer": row["Highest Constructed Issuer"],
                # I'm omitting some fields related to extended validation
                "is_symantec_cert": row["Is Symantec Cert"],
                "symantec_distrust_date": row["Symantec Distrust Date"],
                "errors": row["Errors"],
                "scan_date": date_today,
                "latest": True,
            }
        )
        domains_processed += 1

    print(
        'Successfully imported {} documents to "{}" database on '
        "{}".format(domains_processed, db.name, db.client.address[0])
    )


if __name__ == "__main__":
    main()
