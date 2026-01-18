import bibtexparser
import json
import requests
from urllib.parse import quote
import logging
import argparse
from tqdm import tqdm

# --- ARGUMENT PARSING ---
parser = argparse.ArgumentParser(description="Update BibTeX entries using DBLP.")
parser.add_argument("--bib_file", default="old.bib", help="Path to the input BibTeX file (e.g., references.bib)")
parser.add_argument("--output_file", default= "output.bib",  help="Path to save the updated BibTeX file (e.g., updated_references.bib)")
parser.add_argument("--log_file", default= "log.txt", help="Path for the log file (e.g., citation_diff.log)")
args = parser.parse_args()

BIB_FILE = args.bib_file
OUTPUT_BIB_FILE = args.output_file
LOG_FILE = args.log_file

REVERSED_KEYS = {"author", "booktitle", "doi", "title", "year", 'ID', 'ENTRYTYPE'}


logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- STEP 1: READ AND PARSE BIB FILE ---
def read_bib_file(bib_file):
    with open(bib_file, encoding="utf-8") as f:
        bib_database = bibtexparser.load(f)
    # Convert each entry to JSON object
    entries = [dict(entry) for entry in bib_database.entries]
    return entries


def query_dblp(title):
    """
    Query DBLP for a paper title, then fetch the official BibTeX record.
    """
    # 1. Search for the paper to get its DBLP key
    search_url = f"https://dblp.org/search/publ/api?q={quote(title)}&format=json"
    try:
        resp = requests.get(search_url)
        data = resp.json()
        hits = data['result']['hits'].get('hit')

        if not hits:
            logging.error(f"Error querying DBLP for {title}")
            return None

        # Get the DBLP key for the first result (e.g., "conf/kbse/Chen24")
        dblp_key = hits[0]['info']['key']

        # 2. Fetch the actual BibTeX string using the key
        bib_url = f"https://dblp.org/rec/{dblp_key}.bib"
        bib_resp = requests.get(bib_url)

        if bib_resp.status_code != 200:
            logging.error(f"Error querying DBLP for {title}")
            return None

        # Parse the BibTeX string into a dictionary
        bib_str = bib_resp.text
        parsed_bib = bibtexparser.loads(bib_str)

        if parsed_bib.entries:
            # bibtexparser returns a list of entries; take the first one
            return dict(parsed_bib.entries[0])

        logging.error(f"Error querying DBLP for {title}")
        return None

    except Exception as e:
        logging.error(f"Error querying DBLP for {title}: {e}")
        return None


# --- STEP 3: COMPARE AND LOG DIFFERENCES ---
def compare_entries(old_entry, new_entry):
    differences = {}
    # We ignore the ID when comparing because DBLP's ID will differ from your local bib
    ignored_keys = ['ID', 'ENTRYTYPE']
    for key, value in new_entry.items():
        if key not in ignored_keys:
            # Clean up potential whitespace/braces differences common in BibTeX
            old_val = str(old_entry.get(key, "")).strip("{} ")
            new_val = str(value).strip("{} ")
            if old_val != new_val:
                differences[key] = {"old": old_entry.get(key), "new": value}
    return differences

def main():
    old_entries = read_bib_file(BIB_FILE)
    updated_entries = []

    changed_ids = []
    unchanged_ids = []
    no_title_ids = []
    not_found_ids = []

    for entry in tqdm(old_entries):
        title = entry.get("title")
        entry_id = entry.get('ID')

        if not title:
            no_title_ids.append(entry_id)
            continue

        new_entry = query_dblp(title)
        if new_entry:
            new_entry = {k: new_entry[k] for k in REVERSED_KEYS if k in new_entry}

            diff = compare_entries(entry, new_entry)
            new_entry['ID'] = entry_id  # keep original ID
            if diff:
                changed_ids.append(entry_id)

                updated_entries.append(new_entry)

            else:
                unchanged_ids.append(entry_id)
                updated_entries.append(entry)
        else:
            not_found_ids.append(entry_id)


    # --- LOG SUMMARY ---
    logging.info("=== BibTeX Update Summary ===")
    logging.info(f"Changed IDs ({len(changed_ids)}): {changed_ids}")
    logging.info(f"Unchanged IDs ({len(unchanged_ids)}): {unchanged_ids}")
    logging.info(f"No title IDs ({len(no_title_ids)}): {no_title_ids}")
    logging.info(f"Not found on DBLP IDs ({len(not_found_ids)}): {not_found_ids}")
    logging.info("=============================")

    # Detailed logging per entry
    for entry_id in changed_ids:
        logging.info(f"{entry_id} has been changed (details available in updated file)")
    for entry_id in unchanged_ids:
        logging.info(f"{entry_id} is the same as DBLP")
    for entry_id in no_title_ids:
        logging.warning(f"{entry_id} has no title and was skipped")
    for entry_id in not_found_ids:
        logging.warning(f"{entry_id} not found on DBLP")

    # Write updated BibTeX file
    bib_database = bibtexparser.bibdatabase.BibDatabase()
    bib_database.entries = updated_entries
    with open(OUTPUT_BIB_FILE, "w", encoding="utf-8") as f:
        bibtexparser.dump(bib_database, f)

    print(f"Updated BibTeX saved to {OUTPUT_BIB_FILE}")
    print(f"Differences logged to {LOG_FILE}")


if __name__ == "__main__":
    main()
